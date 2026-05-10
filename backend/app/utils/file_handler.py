import base64
from fastapi import UploadFile
from PIL import Image
import io
from app.config import settings
from app.utils.exceptions import FileTooLargeError, UnsupportedFileTypeError, ImageProcessingError


class FileHandler:
    @staticmethod
    async def validate_image(file: UploadFile) -> None:
        """이미지 파일 검증"""
        # 확장자 검증
        if file.filename:
            ext = f".{file.filename.split('.')[-1].lower()}"
            if ext not in settings.ALLOWED_EXTENSIONS:
                raise UnsupportedFileTypeError(settings.ALLOWED_EXTENSIONS)

        # 파일 크기 검증
        contents = await file.read()
        await file.seek(0)

        size_mb = len(contents) / (1024 * 1024)
        if size_mb > settings.MAX_FILE_SIZE_MB:
            raise FileTooLargeError(settings.MAX_FILE_SIZE_MB)

    @staticmethod
    async def image_to_base64(file: UploadFile) -> str:
        """이미지를 Base64로 변환 (필요시 리사이징)"""
        try:
            contents = await file.read()

            # 이미지 최적화 (필요시 리사이징)
            image = Image.open(io.BytesIO(contents))

            # RGBA를 RGB로 변환 (PNG 투명도 처리)
            if image.mode in ('RGBA', 'LA', 'P'):
                background = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'P':
                    image = image.convert('RGBA')
                background.paste(image, mask=image.split()[-1] if image.mode == 'RGBA' else None)
                image = background

            # 최대 크기 제한 (2048px)
            max_size = 2048
            if max(image.size) > max_size:
                image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

            # JPEG로 변환
            buffer = io.BytesIO()
            image.save(buffer, format='JPEG', quality=85, optimize=True)
            contents = buffer.getvalue()

            return base64.b64encode(contents).decode('utf-8')
        except Exception as e:
            raise ImageProcessingError(f"이미지 처리 실패: {str(e)}")


file_handler = FileHandler()
