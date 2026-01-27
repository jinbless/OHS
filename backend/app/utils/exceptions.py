from fastapi import HTTPException


class OHSException(HTTPException):
    def __init__(self, detail: str, error_code: str, status_code: int = 400):
        super().__init__(status_code=status_code, detail=detail)
        self.error_code = error_code


class ImageProcessingError(OHSException):
    def __init__(self, detail: str = "이미지 처리 중 오류가 발생했습니다."):
        super().__init__(detail, "IMAGE_PROCESSING_ERROR", 422)


class OpenAIAPIError(OHSException):
    def __init__(self, detail: str = "AI 분석 서비스에 오류가 발생했습니다."):
        super().__init__(detail, "OPENAI_API_ERROR", 503)


class FileTooLargeError(OHSException):
    def __init__(self, max_size_mb: int):
        detail = f"파일 크기가 {max_size_mb}MB를 초과합니다."
        super().__init__(detail, "FILE_TOO_LARGE", 413)


class UnsupportedFileTypeError(OHSException):
    def __init__(self, allowed_types: list):
        detail = f"지원하지 않는 파일 형식입니다. 허용: {', '.join(allowed_types)}"
        super().__init__(detail, "UNSUPPORTED_FILE_TYPE", 415)


class AnalysisNotFoundError(OHSException):
    def __init__(self, analysis_id: str):
        detail = f"분석 기록을 찾을 수 없습니다: {analysis_id}"
        super().__init__(detail, "ANALYSIS_NOT_FOUND", 404)
