import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

class Config:
    # Security
    SECRET_KEY = os.getenv("SECRET_KEY")
    if not SECRET_KEY:
        raise ValueError("No SECRET_KEY set. Please set SECRET_KEY in .env file for JWT security.")
    
    # AI Environment
    # Keep backward compatibility with older GOOGLE_API_KEY naming.
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemma-3-27b-it")
    
    # Database
    MONGO_URI = os.getenv("MONGO_URI")
    DATA_FILE = "data/Chatbot_TestData.xlsx" # Legacy file, logic moved to MongoDB

    # RAG Tuning
    RAG_FAST_CONFIDENCE = float(os.getenv("RAG_FAST_CONFIDENCE", "0.72"))
    RAG_REWRITE_TRIGGER = float(os.getenv("RAG_REWRITE_TRIGGER", "0.68"))
    RAG_RERANK_TRIGGER = float(os.getenv("RAG_RERANK_TRIGGER", "0.82"))
    RAG_MAX_EXPANDED_QUERIES = max(0, int(os.getenv("RAG_MAX_EXPANDED_QUERIES", "2")))
    RAG_MAX_TOTAL_QUERIES = max(1, int(os.getenv("RAG_MAX_TOTAL_QUERIES", "3")))
    RAG_ENABLE_HEAVY_PIPELINE = _env_bool("RAG_ENABLE_HEAVY_PIPELINE", True)

    # Constants & Keywords
    WEAK_SERVICE_PHRASES = [
        "temporarily busy",
        "try again in",
        "handling many requests",
        "having trouble processing",
        "temporarily unavailable",
    ]

    GENERAL_CACHE_STOPWORDS = {
        "what", "who", "how", "when", "where", "why", "which", "is", "are", "the",
        "a", "an", "of", "to", "for", "in", "on", "and", "or", "please", "tell",
        "about", "explain", "can", "you", "me", "it"
    }

    PERSONAL_DATA_FIELDS = [
        "STUDENT_NUMBER", "STUDENT_ID", "STUDENT_NAME", "PREFERRED_NAME",
        "PROGRAMME_CODE", "PROGRAMME_NAME", "PROGRAMME", "PROFILE_STATUS",
        "PROFILE_TYPE", "ENROLLMENT_STATUS", "SEMESTER", "INTAKE",
        "CAMPUS", "FACULTY", "NATIONALITY", "GENDER", "EMAIL", "PHONE",
        "HOSTEL", "ADVISOR", "CURRENT_GPA", "CURRENT_CGPA", "GRADES",
        "LATEST_RESULTS", "DOB", "DATE_OF_BIRTH", "GPA", "CGPA"
    ]

    CHAT_CHITCHAT_EXACT = {
        "hi", "hello", "hey", "thanks", "thank you", "bye",
        "good morning", "good afternoon", "good evening"
    }

    RAG_FORCE_KEYWORDS = [
        "ucsi", "campus", "hostel", "dorm", "accommodation",
        "tuition", "fee", "fees", "scholarship",
        "programme", "program", "course", "major", "faculty",
        "lecturer", "professor", "dean", "chancellor", "vice chancellor", "staff",
        "international", "admission", "entry requirement", "requirements",
        "library", "lab", "facility", "facilities", "print", "printer", "prayer",
        "block", "building", "class", "timetable", "schedule",
        "bus", "shuttle", "route", "exam", "semester", "intake", "advisor",
        "gpa", "cgpa", "grade", "result", "student id", "student number"
    ]
