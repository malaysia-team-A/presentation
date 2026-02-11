"""
Language Detection Engine - Auto-detect and respond in user's language
다국어 지원: 한국어/영어/중국어 자동 감지
"""
import re
from typing import Tuple

class LanguageDetector:
    """Simple language detection based on character analysis"""
    
    # Character ranges
    KOREAN_RANGE = (0xAC00, 0xD7A3)  # Hangul syllables
    KOREAN_JAMO = (0x1100, 0x11FF)   # Hangul Jamo
    CHINESE_RANGES = [(0x4E00, 0x9FFF), (0x3400, 0x4DBF)]  # CJK Unified Ideographs
    
    @staticmethod
    def detect(text: str) -> str:
        """
        Detect primary language of text
        Returns: 'ko' (Korean), 'zh' (Chinese), 'en' (English)
        """
        if not text:
            return 'en'
        
        korean_count = 0
        chinese_count = 0
        english_count = 0
        
        for char in text:
            code = ord(char)
            
            # Korean check
            if (LanguageDetector.KOREAN_RANGE[0] <= code <= LanguageDetector.KOREAN_RANGE[1] or
                LanguageDetector.KOREAN_JAMO[0] <= code <= LanguageDetector.KOREAN_JAMO[1]):
                korean_count += 1
            
            # Chinese check
            elif any(start <= code <= end for start, end in LanguageDetector.CHINESE_RANGES):
                chinese_count += 1
            
            # English check (ASCII letters)
            elif char.isalpha() and ord(char) < 128:
                english_count += 1
        
        # Determine primary language
        if korean_count > chinese_count and korean_count > english_count * 0.3:
            return 'ko'
        elif chinese_count > korean_count and chinese_count > english_count * 0.3:
            return 'zh'
        else:
            return 'en'
    
    @staticmethod
    def get_language_name(code: str) -> str:
        """Get full language name"""
        names = {
            'ko': 'Korean',
            'zh': 'Chinese', 
            'en': 'English'
        }
        return names.get(code, 'English')


class MultilingualResponder:
    """Generate language-appropriate responses"""
    
    # Common phrases in different languages
    PHRASES = {
        'greeting': {
            'ko': '안녕하세요! UCSI buddy입니다. 무엇을 도와드릴까요?',
            'zh': '您好！我是 UCSI buddy。有什么可以帮助您的？',
            'en': 'Hello! I\'m Buddy from UCSI buddy. How can I help you?'
        },
        'login_required': {
            'ko': '이 정보를 조회하려면 로그인이 필요합니다.',
            'zh': '查看此信息需要登录。',
            'en': 'You need to log in to access this information.'
        },
        'unlock_required': {
            'ko': '성적 정보를 보려면 UNLOCK 버튼을 눌러 비밀번호를 확인해주세요.',
            'zh': '要查看成绩信息，请点击UNLOCK按钮确认密码。',
            'en': 'To view grade information, please click UNLOCK and verify your password.'
        },
        'not_found': {
            'ko': '죄송합니다, 해당 정보를 찾을 수 없습니다.',
            'zh': '抱歉，找不到相关信息。',
            'en': 'Sorry, I couldn\'t find that information.'
        },
        'error': {
            'ko': '오류가 발생했습니다. 다시 시도해주세요.',
            'zh': '发生错误，请重试。',
            'en': 'An error occurred. Please try again.'
        },
        'thanks': {
            'ko': '피드백 감사합니다!',
            'zh': '感谢您的反馈！',
            'en': 'Thanks for your feedback!'
        }
    }
    
    @staticmethod
    def get_phrase(key: str, lang: str = 'en') -> str:
        """Get a phrase in the specified language"""
        phrases = MultilingualResponder.PHRASES.get(key, {})
        return phrases.get(lang, phrases.get('en', ''))
    
    @staticmethod
    def get_ai_language_instruction(lang: str) -> str:
        """Get instruction for AI to respond in specific language"""
        instructions = {
            'ko': 'IMPORTANT: Respond in Korean (한국어로 답변하세요).',
            'zh': 'IMPORTANT: Respond in Chinese (请用中文回答).',
            'en': 'Respond in English.'
        }
        return instructions.get(lang, instructions['en'])


# Singleton
language_detector = LanguageDetector()
multilingual = MultilingualResponder()


def detect_language(text: str) -> str:
    """Convenience function to detect language"""
    return language_detector.detect(text)


def get_localized_phrase(key: str, text: str) -> str:
    """Get phrase localized to detected language of text"""
    lang = detect_language(text)
    return multilingual.get_phrase(key, lang)


if __name__ == "__main__":
    # Test
    tests = [
        "Hello, how are you?",
        "안녕하세요, 제 학점 알려주세요",
        "你好，我想查询我的成绩",
        "What is my GPA?"
    ]
    
    for text in tests:
        lang = detect_language(text)
        print(f"'{text[:30]}...' -> {lang} ({language_detector.get_language_name(lang)})")
