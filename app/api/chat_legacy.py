import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from app.config import Config
from app.core.session import (
    append_conversation_message,
    get_conversation_history,
    high_security_sessions,
)
from app.engines.ai_engine_async import ai_engine_async
from app.engines.db_engine_async import db_engine_async
from app.engines.rag_engine_async import rag_engine_async
from app.engines.semantic_router_async import semantic_router_async
from app.api.chat_helpers import (
    _build_suggestions,
    _capability_smalltalk_response,
    _capability_suggestions,
    _compose_no_data_response,
    _detect_language,
    _extract_person_candidate,
    _extract_rag_meta,
    _format_personal_info,
    _has_ucsi_context,
    _infer_preferred_labels,
    _is_capability_smalltalk_query,
    _is_document_limited_answer,
    _is_grade_query,
    _is_personal_query,
    _personal_info_suggestions,
    _resolve_session,
    _should_force_rag,
    _user_display_name,
    _user_student_number,
)
from app.schemas import ChatRequest, FeedbackRequest
from app.utils.auth_utils import decode_access_token

router = APIRouter()


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


LLM_ROUTER_MIN_CONFIDENCE = _env_float("LLM_ROUTER_MIN_CONFIDENCE", 0.55)


def _preferred_labels_from_intent(intent: Optional[str]) -> list:
    mapping = {
        "ucsi_programme": ["Programme"],
        "ucsi_hostel": ["Hostel", "HostelFAQ"],
        "ucsi_staff": ["Staff"],
        "ucsi_facility": ["Facility"],
        "ucsi_schedule": ["Schedule"],
    }
    labels = mapping.get(str(intent or "").strip(), [])
    return list(labels)


async def _log_rag_miss(
    *,
    conversation_id: str,
    user_message: str,
    query: str,
    rag_meta: Dict[str, Any],
    reason: str,
) -> None:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "conversation_id": conversation_id,
        "question": user_message,
        "search_query": query,
        "confidence": rag_meta.get("confidence", 0.0),
        "sources": rag_meta.get("sources", []),
        "reason": reason,
    }
    try:
        await db_engine_async.log_unanswered(payload)
    except Exception:
        pass


@router.post("/chat")
async def chat(body: ChatRequest, request: Request):
    user = None
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        user = decode_access_token(auth_header.split(" ", 1)[1].strip())

    session_key, conversation_id, _ = _resolve_session(user, body)
    user_msg = (body.message or "").strip()
    if not user_msg:
        return {"error": "Message is required", "session_id": conversation_id}

    append_conversation_message(session_key, "user", user_msg)
    history = get_conversation_history(session_key)
    user_lang = _detect_language(user_msg)

    search_term = (body.search_term or "").strip() or None
    context_text = ""
    is_personal_rule = _is_personal_query(user_msg, search_term)
    is_personal = is_personal_rule
    person_candidate: Optional[str] = None
    person_resolution: Optional[Dict[str, Any]] = None
    feedback_bad_guard = False
    decision_force_rag = False
    rlhf_policy: Dict[str, Any] = {"has_signal": False}
    last_rag_query = str(search_term or user_msg)
    planner_decision = await ai_engine_async.plan_intent(
        user_message=user_msg,
        conversation_history=history,
        language=user_lang,
        search_term=search_term,
    )
    semantic_decision = await semantic_router_async.classify(
        user_message=user_msg,
        search_term=search_term,
        language=user_lang,
        conversation_history=history,
    )

    planner_intent = str((planner_decision or {}).get("intent") or "").strip()
    planner_confidence = float((planner_decision or {}).get("confidence") or 0.0)
    semantic_intent = str((semantic_decision or {}).get("intent") or "").strip()
    semantic_confidence = float((semantic_decision or {}).get("confidence") or 0.0)

    use_planner = bool(
        planner_intent
        and planner_intent != "unknown"
        and planner_confidence >= LLM_ROUTER_MIN_CONFIDENCE
    )
    active_decision = planner_decision if use_planner else (semantic_decision or planner_decision or {})
    active_intent = str((active_decision or {}).get("intent") or "").strip()
    active_entity = str((active_decision or {}).get("entity") or "").strip()

    retrieval_meta: Dict[str, Any] = {
        "route": "general_ai",
        "used": False,
        "confidence": 0.0,
        "sources": [],
        "route_decision": {
            "is_personal_rule": bool(is_personal_rule),
            "planner_intent": planner_intent,
            "planner_confidence": planner_confidence,
            "planner_used": use_planner,
            "semantic_intent": semantic_intent,
            "semantic_confidence": semantic_confidence,
            "semantic_used_history": bool(
                (semantic_decision or {}).get("used_history_context")
            ),
        },
    }
    route_decision = dict(retrieval_meta.get("route_decision") or {})

    def _attach_rlhf(meta: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(meta, dict):
            return meta
        if not (rlhf_policy or {}).get("has_signal"):
            return meta
        meta["rlhf"] = {
            "has_signal": True,
            "strict_grounding": bool((rlhf_policy or {}).get("strict_grounding")),
            "signal_count": int((rlhf_policy or {}).get("signal_count") or 0),
            "top_tags": list((rlhf_policy or {}).get("top_tags") or [])[:3],
        }
        return meta

    # Keep deterministic smalltalk fallback only when planner is not trusted.
    if not use_planner and (
        active_intent == "capability_smalltalk" or _is_capability_smalltalk_query(user_msg)
    ):
        capability_meta = {
            "route": "capability_smalltalk",
            "used": False,
            "confidence": float((active_decision or {}).get("confidence") or 1.0),
            "sources": [],
            "route_decision": retrieval_meta.get("route_decision", {}),
        }
        response_payload = {
            "text": _capability_smalltalk_response(user_msg),
            "suggestions": _build_suggestions(
                user_message=user_msg,
                user_lang=user_lang,
                retrieval_meta=capability_meta,
                ai_suggestions=_capability_suggestions(user_lang),
                is_personal=False,
                search_term=search_term,
                person_resolution=person_resolution,
            ),
            "retrieval": capability_meta,
        }
        append_conversation_message(session_key, "model", json.dumps(response_payload))
        return {
            "response": json.dumps(response_payload),
            "session_id": conversation_id,
            "type": "message",
            "user": _user_display_name(user),
        }

    if (active_decision or {}).get("is_personal"):
        is_personal = True

    if active_intent == "general_person" and active_entity:
        person_candidate = active_entity
        person_resolution = {
            "candidate": active_entity,
            "match_type": "general_person",
            "source": "llm_planner" if use_planner else "semantic_router",
        }

    if (active_decision or {}).get("needs_context"):
        decision_force_rag = True
        decision_search = str((active_decision or {}).get("search_term") or "").strip()
        if decision_search and not search_term:
            search_term = decision_search

    if not is_personal:
        learned_answer = await db_engine_async.search_learned_response(user_msg)
        if learned_answer:
            retrieval_meta = {
                "route": "feedback_learned_qa",
                "used": True,
                "confidence": 1.0,
                "sources": ["MongoDB:LearnedQA"],
                "route_decision": route_decision,
            }
            response_payload = {
                "text": learned_answer,
                "suggestions": _build_suggestions(
                    user_message=user_msg,
                    user_lang=user_lang,
                    retrieval_meta=retrieval_meta,
                    ai_suggestions=[],
                    is_personal=False,
                    search_term=search_term,
                    person_resolution=person_resolution,
                ),
                "retrieval": retrieval_meta,
            }
            append_conversation_message(session_key, "model", json.dumps(response_payload))
            return {
                "response": json.dumps(response_payload),
                "session_id": conversation_id,
                "type": "message",
                "user": _user_display_name(user),
            }

    force_rag = bool(
        body.needs_context
        or search_term
        or decision_force_rag
        or _should_force_rag(user_msg)
    )
    if use_planner:
        force_rag = bool(body.needs_context or decision_force_rag or search_term)
    if active_intent == "general_world" and not body.needs_context and not search_term:
        force_rag = False

    if not is_personal and not search_term:
        lookup_candidate = person_candidate or _extract_person_candidate(user_msg)
        if lookup_candidate:
            person_candidate = lookup_candidate
            staff_match = await db_engine_async.find_staff_by_name(lookup_candidate)
            if staff_match:
                force_rag = True
                search_term = lookup_candidate
                active_intent = "ucsi_staff"
                person_resolution = {
                    "candidate": lookup_candidate,
                    "match_type": "db_staff_match",
                    "matched_name": staff_match.get("name"),
                }
                route_decision["db_staff_match"] = True
            else:
                student_match = await db_engine_async.get_student_by_name(lookup_candidate)
                if student_match:
                    person_resolution = {
                        "candidate": lookup_candidate,
                        "match_type": "db_student_private_match",
                        "matched_name": str(student_match.get("STUDENT_NAME") or "").strip()
                        or lookup_candidate,
                    }
                    route_decision["db_student_name_match"] = True
                elif _has_ucsi_context(user_msg):
                    force_rag = True
                    search_term = lookup_candidate
                    person_resolution = {
                        "candidate": lookup_candidate,
                        "match_type": "ucsi_context_no_match",
                    }
                elif person_resolution is None:
                    person_resolution = {
                        "candidate": lookup_candidate,
                        "match_type": "general_person",
                    }

    if (
        isinstance(person_resolution, dict)
        and person_resolution.get("match_type") == "db_student_private_match"
    ):
        candidate = str(person_resolution.get("matched_name") or person_resolution.get("candidate") or "").strip() or "this person"
        clarification = (
            f"'{candidate}' 이름이 학내 학생 데이터와 겹칠 수 있어요. "
            "개인정보 보호를 위해 임의 인물 조회는 제공하지 않아요. "
            "UCSI 교직원 정보인지, 일반 인물(예: 연예인/역사인물)인지 구체적으로 알려주세요."
            if user_lang == "ko"
            else (
                f"The name '{candidate}' may overlap with student records in our campus data. "
                "For privacy reasons, I do not provide arbitrary student lookups. "
                "Please clarify whether you mean a UCSI staff member or a public figure."
            )
        )
        retrieval_meta = {
            "route": "person_disambiguation_guard",
            "used": False,
            "confidence": 1.0,
            "sources": [],
            "route_decision": route_decision,
            "person_resolution": person_resolution,
        }
        response_payload = {
            "text": clarification,
            "suggestions": _build_suggestions(
                user_message=user_msg,
                user_lang=user_lang,
                retrieval_meta=retrieval_meta,
                ai_suggestions=[],
                is_personal=False,
                search_term=search_term,
                person_resolution=person_resolution,
            ),
            "retrieval": retrieval_meta,
        }
        append_conversation_message(session_key, "model", json.dumps(response_payload))
        return {
            "response": json.dumps(response_payload),
            "session_id": conversation_id,
            "type": "message",
            "user": _user_display_name(user),
        }

    if person_resolution:
        retrieval_meta["person_resolution"] = person_resolution

    if not is_personal:
        feedback_bad_guard = await db_engine_async.has_bad_response(user_msg)
        if feedback_bad_guard:
            force_rag = True
        try:
            rlhf_policy = await db_engine_async.get_rlhf_policy(user_msg)
        except Exception:
            rlhf_policy = {"has_signal": False}
        retrieval_meta = _attach_rlhf(retrieval_meta)

    if is_personal:
        student_number = _user_student_number(user)
        if not student_number:
            return {
                "response": "Please login to access personal information.",
                "type": "login_hint",
                "conversation_id": conversation_id,
                "session_id": conversation_id,
            }

        expiry = high_security_sessions.get(student_number)
        high_security_active = bool(expiry and expiry >= datetime.now())
        if expiry and expiry < datetime.now():
            high_security_sessions.pop(student_number, None)

        if _is_grade_query(user_msg, search_term) and not high_security_active:
            prompt_text = (
                "GPA/성적 정보를 보려면 비밀번호 인증이 필요해요."
                if user_lang == "ko"
                else "Please verify your password to access GPA/grade information."
            )
            return {
                "response": prompt_text,
                "type": "password_prompt",
                "conversation_id": conversation_id,
                "session_id": conversation_id,
            }

        student_data = await db_engine_async.get_student_by_number(student_number)
        if student_data:
            retrieval_meta = {
                "route": "personal_db_direct",
                "used": True,
                "confidence": 1.0,
                "sources": ["MongoDB:Student"],
                "route_decision": route_decision,
            }
            response_payload = {
                "text": _format_personal_info(
                    student_data,
                    user_msg,
                    search_term,
                    allow_sensitive=high_security_active,
                ),
                "suggestions": _build_suggestions(
                    user_message=user_msg,
                    user_lang=user_lang,
                    retrieval_meta=retrieval_meta,
                    ai_suggestions=_personal_info_suggestions(
                        user_lang, allow_sensitive=high_security_active
                    ),
                    is_personal=True,
                    search_term=search_term,
                    person_resolution=person_resolution,
                ),
                "retrieval": retrieval_meta,
            }
            append_conversation_message(session_key, "model", json.dumps(response_payload))
            return {
                "response": json.dumps(response_payload),
                "session_id": conversation_id,
                "type": "message",
                "user": _user_display_name(user),
            }
        else:
            retrieval_meta = {
                "route": "personal_db_direct",
                "used": True,
                "confidence": 0.0,
                "sources": ["MongoDB:Student"],
                "route_decision": route_decision,
            }
            missing_text = (
                "학생 정보를 찾지 못했어요. 학번/이름을 다시 확인해 주세요."
                if user_lang == "ko"
                else "I could not find your student profile. Please verify your student account."
            )
            response_payload = {
                "text": missing_text,
                "suggestions": _build_suggestions(
                    user_message=user_msg,
                    user_lang=user_lang,
                    retrieval_meta=retrieval_meta,
                    ai_suggestions=_personal_info_suggestions(
                        user_lang, allow_sensitive=high_security_active
                    ),
                    is_personal=True,
                    search_term=search_term,
                    person_resolution=person_resolution,
                ),
                "retrieval": retrieval_meta,
            }
            append_conversation_message(session_key, "model", json.dumps(response_payload))
            return {
                "response": json.dumps(response_payload),
                "session_id": conversation_id,
                "type": "message",
                "user": _user_display_name(user),
            }

    elif force_rag:
        query = str(search_term or user_msg)
        last_rag_query = query
        preferred_labels = _infer_preferred_labels(user_msg, search_term)
        for label in _preferred_labels_from_intent(active_intent):
            if label not in preferred_labels:
                preferred_labels.insert(0, label)
        if person_resolution and person_resolution.get("match_type") == "db_staff_match":
            if "Staff" not in preferred_labels:
                preferred_labels.insert(0, "Staff")
        rag_result = await rag_engine_async.search_context(
            query=query,
            top_k=5,
            preferred_labels=preferred_labels,
        )
        rag_meta = _extract_rag_meta(rag_result)
        retrieval_meta = {
            "route": "rag",
            "used": True,
            "confidence": rag_meta["confidence"],
            "sources": rag_meta["sources"],
            "preferred_labels": preferred_labels,
            "route_decision": route_decision,
        }
        retrieval_meta = _attach_rlhf(retrieval_meta)
        if feedback_bad_guard:
            retrieval_meta["feedback_guard"] = True
        if person_resolution:
            retrieval_meta["person_resolution"] = person_resolution
        context_text = rag_meta["context"] or "[NO_RELEVANT_DATA_FOUND]"
        if feedback_bad_guard:
            context_text = (
                "[FEEDBACK_GUARD] A previous answer for this query was marked incorrect. "
                "Do not repeat it; rely only on verified context.\n\n"
                + context_text
            )

        if not rag_meta["has_relevant_data"]:
            await _log_rag_miss(
                conversation_id=conversation_id,
                user_message=user_msg,
                query=query,
                rag_meta=rag_meta,
                reason="no_relevant_data",
            )
            response_payload = {
                "text": _compose_no_data_response(),
                "suggestions": _build_suggestions(
                    user_message=user_msg,
                    user_lang=user_lang,
                    retrieval_meta=retrieval_meta,
                    ai_suggestions=[],
                    is_personal=False,
                    search_term=search_term,
                    person_resolution=person_resolution,
                ),
                "retrieval": retrieval_meta,
            }
            append_conversation_message(session_key, "model", json.dumps(response_payload))
            return {
                "response": json.dumps(response_payload),
                "session_id": conversation_id,
                "type": "message",
                "user": _user_display_name(user),
            }

    ai_result = None
    if context_text:
        if (
            not is_personal
            and bool((rlhf_policy or {}).get("strict_grounding"))
            and retrieval_meta.get("used")
            and float(retrieval_meta.get("confidence", 0.0)) < float(Config.RAG_FAST_CONFIDENCE)
            and "[NO_RELEVANT_DATA_FOUND]" not in context_text
        ):
            await _log_rag_miss(
                conversation_id=conversation_id,
                user_message=user_msg,
                query=last_rag_query,
                rag_meta={
                    "confidence": retrieval_meta.get("confidence", 0.0),
                    "sources": retrieval_meta.get("sources", []),
                },
                reason="rlhf_strict_low_confidence",
            )
            response_payload = {
                "text": _compose_no_data_response(),
                "suggestions": _build_suggestions(
                    user_message=user_msg,
                    user_lang=user_lang,
                    retrieval_meta=retrieval_meta,
                    ai_suggestions=[],
                    is_personal=False,
                    search_term=search_term,
                    person_resolution=person_resolution,
                ),
                "retrieval": retrieval_meta,
            }
            append_conversation_message(session_key, "model", json.dumps(response_payload))
            return {
                "response": json.dumps(response_payload),
                "session_id": conversation_id,
                "type": "message",
                "user": _user_display_name(user),
            }

        if retrieval_meta.get("used") and retrieval_meta.get("confidence", 0.0) < float(
            Config.RAG_FAST_CONFIDENCE
        ):
            context_text = (
                "[LOW_CONFIDENCE_CONTEXT] Some matches are weak. Avoid overclaiming.\n\n"
                + context_text
            )
        ai_result = await ai_engine_async.process_message(
            user_message=user_msg,
            data_context=context_text,
            conversation_history=history,
            language=user_lang,
            query_scope_hint=(
                "general_person"
                if isinstance(person_resolution, dict)
                and person_resolution.get("match_type") == "general_person"
                else None
            ),
            rlhf_policy_hint=str((rlhf_policy or {}).get("policy_hint") or "").strip() or None,
        )
    else:
        if use_planner:
            planner_search = str((active_decision or {}).get("search_term") or "").strip()
            initial_result = {
                "needs_context": bool((active_decision or {}).get("needs_context")),
                "search_term": planner_search or search_term,
                "suggestions": [],
            }
        else:
            # Fallback planner path if LLM intent planner is unavailable/low-confidence.
            initial_result = await ai_engine_async.process_message(
                user_message=user_msg,
                data_context="",
                conversation_history=history,
                language=user_lang,
                query_scope_hint=(
                    "general_person"
                    if isinstance(person_resolution, dict)
                    and person_resolution.get("match_type") == "general_person"
                    else None
                ),
                rlhf_policy_hint=str((rlhf_policy or {}).get("policy_hint") or "").strip() or None,
            )
        # General person queries (not tied to UCSI) should not be forced into RAG no-data responses.
        if (
            isinstance(person_resolution, dict)
            and person_resolution.get("match_type") == "general_person"
        ):
            initial_result["needs_context"] = False

        if initial_result.get("needs_context"):
            query = (
                initial_result.get("search_term")
                or search_term
                or user_msg
            )
            last_rag_query = str(query)
            preferred_labels = _infer_preferred_labels(user_msg, str(query))
            for label in _preferred_labels_from_intent(active_intent):
                if label not in preferred_labels:
                    preferred_labels.insert(0, label)
            rag_result = await rag_engine_async.search_context(
                query=str(query),
                top_k=5,
                preferred_labels=preferred_labels,
            )
            rag_meta = _extract_rag_meta(rag_result)
            retrieval_meta = {
                "route": "planner_rag",
                "used": True,
                "confidence": rag_meta["confidence"],
                "sources": rag_meta["sources"],
                "preferred_labels": preferred_labels,
                "route_decision": route_decision,
            }
            retrieval_meta = _attach_rlhf(retrieval_meta)
            if feedback_bad_guard:
                retrieval_meta["feedback_guard"] = True
            if person_resolution:
                retrieval_meta["person_resolution"] = person_resolution
            context_text = rag_meta["context"] or "[NO_RELEVANT_DATA_FOUND]"
            if feedback_bad_guard:
                context_text = (
                    "[FEEDBACK_GUARD] A previous answer for this query was marked incorrect. "
                    "Do not repeat it; rely only on verified context.\n\n"
                    + context_text
                )

            if rag_meta["has_relevant_data"]:
                if rag_meta["confidence"] < float(Config.RAG_FAST_CONFIDENCE):
                    context_text = (
                        "[LOW_CONFIDENCE_CONTEXT] Some matches are weak. Avoid overclaiming.\n\n"
                        + context_text
                    )
                ai_result = await ai_engine_async.process_message(
                    user_message=user_msg,
                    data_context=context_text,
                    conversation_history=history,
                    language=user_lang,
                    query_scope_hint=(
                        "general_person"
                        if isinstance(person_resolution, dict)
                        and person_resolution.get("match_type") == "general_person"
                        else None
                    ),
                    rlhf_policy_hint=str((rlhf_policy or {}).get("policy_hint") or "").strip() or None,
                )
            else:
                await _log_rag_miss(
                    conversation_id=conversation_id,
                    user_message=user_msg,
                    query=str(query),
                    rag_meta=rag_meta,
                    reason="planner_no_relevant_data",
                )
                fallback_text = ""
                if not use_planner:
                    fallback_text = str(initial_result.get("response") or "").strip()
                if fallback_text and not force_rag:
                    ai_result = {
                        "response": fallback_text,
                        "suggestions": _build_suggestions(
                            user_message=user_msg,
                            user_lang=user_lang,
                            retrieval_meta=retrieval_meta,
                            ai_suggestions=initial_result.get("suggestions", []),
                            is_personal=False,
                            search_term=search_term,
                            person_resolution=person_resolution,
                        ),
                    }
                else:
                    ai_result = {
                        "response": _compose_no_data_response(),
                        "suggestions": _build_suggestions(
                            user_message=user_msg,
                            user_lang=user_lang,
                            retrieval_meta=retrieval_meta,
                            ai_suggestions=[],
                            is_personal=False,
                            search_term=search_term,
                            person_resolution=person_resolution,
                        ),
                    }
        else:
            if use_planner:
                ai_result = await ai_engine_async.process_message(
                    user_message=user_msg,
                    data_context="",
                    conversation_history=history,
                    language=user_lang,
                    query_scope_hint=(
                        "general_person"
                        if isinstance(person_resolution, dict)
                        and person_resolution.get("match_type") == "general_person"
                        else None
                    ),
                    rlhf_policy_hint=str((rlhf_policy or {}).get("policy_hint") or "").strip() or None,
                )
            else:
                ai_result = initial_result

    response_text = str((ai_result or {}).get("response") or "I'm not sure how to respond.")
    if (
        isinstance(person_resolution, dict)
        and person_resolution.get("match_type") == "general_person"
        and _is_document_limited_answer(response_text)
    ):
        candidate = str(person_resolution.get("candidate") or "").strip() or "해당 인물"
        if user_lang == "ko":
            response_text = (
                f"'{candidate}'은(는) 일반 인물 질의로 처리할게요. "
                "동명이인이 있을 수 있으니 분야(예: 가수/연구자/교수)를 알려주면 더 정확히 답할 수 있어요."
            )
        else:
            response_text = (
                f"I will treat '{candidate}' as a general person query. "
                "If there are multiple people with the same name, share a field (e.g., singer/researcher/professor) for a more accurate answer."
            )
    suggestions = _build_suggestions(
        user_message=user_msg,
        user_lang=user_lang,
        retrieval_meta=retrieval_meta,
        ai_suggestions=(ai_result or {}).get("suggestions") or [],
        is_personal=False,
        search_term=search_term,
        person_resolution=person_resolution,
    )

    response_payload = {
        "text": response_text,
        "suggestions": suggestions[:3],
        "retrieval": retrieval_meta,
    }
    append_conversation_message(session_key, "model", json.dumps(response_payload))

    return {
        "response": json.dumps(response_payload),
        "session_id": conversation_id,
        "type": "message",
        "user": _user_display_name(user),
    }


@router.post("/feedback")
async def feedback(body: FeedbackRequest):
    user_message = str(body.user_message or "").strip()
    ai_response = str(body.ai_response or "").strip()
    comment = None if body.comment is None else str(body.comment).strip()
    rating = str(body.rating or "").strip().lower()
    session_id = str(body.session_id or "guest_session").strip() or "guest_session"
    payload = {
        "user_message": user_message,
        "ai_response": ai_response,
        "rating": rating,
        "comment": comment or None,
        "session_id": session_id,
    }
    payload["timestamp"] = datetime.now().isoformat()
    saved = await db_engine_async.save_feedback(payload)

    if saved and user_message and ai_response:
        if rating == "positive":
            await db_engine_async.save_learned_response(user_message, ai_response)
        elif rating == "negative":
            await db_engine_async.save_bad_response(
                user_message,
                ai_response,
                reason=comment or "User marked as incorrect",
            )

    return {"success": bool(saved), "status": "success" if saved else "error"}


@router.get("/export_chat")
async def export_chat(request: Request):
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return {
            "success": False,
            "message": "Token is missing",
        }

    user = decode_access_token(auth_header.split(" ", 1)[1].strip())
    student_number = _user_student_number(user)
    if not student_number:
        return {
            "success": False,
            "message": "Invalid or expired token",
        }

    session_key = f"user:{student_number}"
    return {
        "success": True,
        "session_id": student_number,
        "messages": get_conversation_history(session_key),
    }
