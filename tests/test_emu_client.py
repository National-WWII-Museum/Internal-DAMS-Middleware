from unittest.mock import MagicMock, patch

from middleware import emu_client


def make_response(matches, next_search=None):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"matches": matches}
    resp.headers = {"Next-Search": next_search} if next_search else {}
    return resp


@patch("middleware.emu_client.get_auth_headers", return_value={"Authorization": "Bearer fake-token"})
@patch("middleware.emu_client.requests.get")
def test_single_page(mock_get, mock_auth):
    mock_get.return_value = make_response(
        matches=[{"data": {"irn": "1"}}, {"data": {"irn": "2"}}]
    )

    records = emu_client.search_modified_since("ecatalogue", "2026-01-01")

    assert records == [{"irn": "1"}, {"irn": "2"}]
    assert mock_get.call_count == 1

    kwargs = mock_get.call_args.kwargs
    assert kwargs["headers"] == {"Authorization": "Bearer fake-token"}
    assert kwargs["params"]["select"] == ";".join(emu_client.PLACEHOLDER_FIELDS)
    assert "2026-01-01" in kwargs["params"]["filter"]


@patch("middleware.emu_client.get_auth_headers", return_value={"Authorization": "Bearer fake-token"})
@patch("middleware.emu_client.requests.get")
def test_pagination_follows_next_search(mock_get, mock_auth):
    page1 = make_response(matches=[{"data": {"irn": "1"}}], next_search="abc123")
    page2 = make_response(matches=[{"data": {"irn": "2"}}])
    mock_get.side_effect = [page1, page2]

    records = emu_client.search_modified_since("ecatalogue", "2026-01-01", page_size=1)

    assert records == [{"irn": "1"}, {"irn": "2"}]
    assert mock_get.call_count == 2

    first_kwargs = mock_get.call_args_list[0].kwargs
    second_kwargs = mock_get.call_args_list[1].kwargs

    assert "filter" in first_kwargs["params"]
    assert "filter" not in second_kwargs["params"]
    assert second_kwargs["headers"]["Next-Search"] == "abc123"


@patch("middleware.emu_client.get_auth_headers", return_value={"Authorization": "Bearer fake-token"})
@patch("middleware.emu_client.requests.get")
def test_custom_fields_joined_with_semicolon(mock_get, mock_auth):
    mock_get.return_value = make_response(matches=[])

    emu_client.search_modified_since(
        "ecatalogue", "2026-01-01", fields=["data.irn", "data.WebTitle"]
    )

    kwargs = mock_get.call_args.kwargs
    assert kwargs["params"]["select"] == "data.irn;data.WebTitle"
