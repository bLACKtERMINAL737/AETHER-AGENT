import base64

import pytest
from pydantic import ValidationError

from aether.app import ChatRequest


def data_url(media_type: str, payload: bytes) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:image/{media_type};base64,{encoded}"


def test_chat_request_accepts_png_signature_and_preserves_data_url():
    image = data_url("png", b"\x89PNG\r\n\x1a\nsmall-test-payload")
    request = ChatRequest(message="Describe it", image_data_url=image)
    assert request.image_data_url == image


def test_chat_request_accepts_jpeg_signature():
    request = ChatRequest(message="Describe it", image_data_url=data_url("jpeg", b"\xff\\xd8\xffpayload"))
    assert request.image_data_url.startswith("data:image/jpeg;base64,")


def test_chat_request_accepts_webp_signature():
    request = ChatRequest(message="Describe it", image_data_url=data_url("webp", b"RIFF\x04\x00\x00\x00WEBPpayload"))
    assert request.image_data_url.startswith("data:image/webp;base64,")


@pytest.mark.parametrize("value", [
    "https://example.test/image.png",
    "data:image/gif;base64,R0lGODlh",
    "data:image/png;base64,not base64!",
    data_url("png", b"not-a-png"),
    data_url("jpeg", b"\x89PNG\r\n\x1a\nwrong-declared-type"),
    "data:image/png;base64,",
])
def test_chat_request_rejects_invalid_image_data_urls(value):
    with pytest.raises(ValidationError):
        ChatRequest(message="Describe it", image_data_url=value)


def test_chat_request_rejects_decoded_image_over_600_kib():
    oversized_png = b"\x89PNG\r\n\x1a\n" + b"x" * (600 * 1024)
    with pytest.raises(ValidationError):
        ChatRequest(message="Describe it", image_data_url=data_url("png", oversized_png))


def test_chat_request_allows_text_only_request():
    request = ChatRequest(message="Hello")
    assert request.image_data_url is None
