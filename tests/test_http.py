import httpx
import pytest

from signal_pipeline.common.http import HttpClient, Outcome, classify_status, redact


def make_client(responses: list[int | Exception]) -> HttpClient:
    """응답을 순서대로 돌려주는 가짜 서버. 간격·백오프 대기는 0으로 둔다."""
    queue = iter(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        item = next(queue)
        if isinstance(item, Exception):
            raise item
        return httpx.Response(item, content=b"%PDF-1.4" if item == 200 else b"error")

    return HttpClient(
        "test", min_interval=0, backoff_base=0, transport=httpx.MockTransport(handler)
    )


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (200, Outcome.SUCCESS),
        (401, Outcome.CONFIG_ERROR),
        (403, Outcome.CONFIG_ERROR),
        (429, Outcome.RATE_LIMITED),
        (404, Outcome.PERMANENT_FAILED),
        (500, Outcome.RETRYABLE_FAILED),
        (503, Outcome.RETRYABLE_FAILED),
    ],
)
def test_classify_status(status: int, expected: Outcome) -> None:
    assert classify_status(status) is expected


def test_retry_then_success_records_every_try() -> None:
    result = make_client([503, 503, 200]).fetch("https://example.test/a")
    assert result.outcome is Outcome.SUCCESS
    assert [t.outcome for t in result.tries] == [
        Outcome.RETRYABLE_FAILED,
        Outcome.RETRYABLE_FAILED,
        Outcome.SUCCESS,
    ]
    assert [t.attempt_no for t in result.tries] == [1, 2, 3]
    assert result.content == b"%PDF-1.4"


def test_timeout_gives_up_after_first_try_plus_five_retries() -> None:
    result = make_client([httpx.ReadTimeout("timeout")] * 6).fetch(
        "https://example.test/a"
    )
    assert result.outcome is Outcome.RETRYABLE_FAILED
    assert len(result.tries) == 6
    assert result.content is None


@pytest.mark.parametrize("status", [401, 403, 404, 429])
def test_no_retry_for_non_retryable(status: int) -> None:
    result = make_client([status]).fetch("https://example.test/a")
    assert len(result.tries) == 1
    assert result.content is None


def test_secrets_are_not_recorded() -> None:
    params = {"crtfc_key": "SECRET", "serviceKey": "S", "rcept_no": "20261002000026"}
    result = make_client([200]).fetch("https://example.test/a?x=1", params=params)
    assert result.endpoint == "https://example.test/a"
    assert result.request_params == {"rcept_no": "20261002000026"}
    assert redact({"AUTH_KEY": "K", "authKey": "K", "page": "1"}) == {"page": "1"}
