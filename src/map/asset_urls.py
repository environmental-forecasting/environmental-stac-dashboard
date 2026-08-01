"""Rewrite STAC asset hrefs for TiTiler on the Docker network."""


def to_tiler_asset_url(
    href: str, file_server_url: str, file_server_internal_url: str
) -> str:
    """
    Rewrite public file-server hrefs so TiTiler can fetch them internally.

    Args:
        href: Public or already-internal asset href.
        file_server_url: Public file-server prefix used in STAC hrefs.
        file_server_internal_url: File-server URL reachable from TiTiler.

    Returns:
        Href suitable for TiTiler's ``url`` query parameter.
    """
    if not file_server_url or not file_server_internal_url:
        return href
    public = file_server_url.rstrip("/")
    internal = file_server_internal_url.rstrip("/")
    if href == public or href.startswith(public + "/"):
        return internal + href[len(public) :]
    return href
