"""Ссылки «открыть в GitLab/GitHub/Gitea/Bitbucket» на строку кода."""

from __future__ import annotations

from urllib.parse import quote, urlsplit

from app.models.entity import RepoType


def guess_repo_type(url: str) -> RepoType | None:
    host = urlsplit(url).netloc.lower()
    for rtype in RepoType:
        if rtype.value in host:
            return rtype
    return None


def build_code_url(
    *,
    repo_url: str | None,
    repo_type: RepoType | None,
    ref: str | None,
    path: str | None,
    line: int | None,
    ref_is_commit: bool,
    path_prefix: str | None = None,
) -> str | None:
    if not (repo_url and ref and path):
        return None
    if urlsplit(repo_url).scheme not in ("http", "https"):
        return None
    rtype = repo_type or guess_repo_type(repo_url)
    if rtype is None:
        return None

    repo = repo_url.strip().rstrip("/")
    if repo.endswith(".git"):
        repo = repo[:-4]
    file_path = path.replace("\\", "/")
    while file_path.startswith("./"):
        file_path = file_path[2:]
    file_path = file_path.lstrip("/")
    prefix = (path_prefix or "").strip("/")
    if prefix and not file_path.startswith(prefix + "/"):
        file_path = f"{prefix}/{file_path}"

    qpath = quote(file_path, safe="/")
    qref = quote(ref, safe="/")
    if rtype == RepoType.gitlab:
        url, anchor = f"{repo}/-/blob/{qref}/{qpath}", f"#L{line}"
    elif rtype == RepoType.github:
        url, anchor = f"{repo}/blob/{qref}/{qpath}", f"#L{line}"
    elif rtype == RepoType.gitea:
        kind = "commit" if ref_is_commit else "branch"
        url, anchor = f"{repo}/src/{kind}/{qref}/{qpath}", f"#L{line}"
    else:
        url, anchor = f"{repo}/browse/{qpath}?at={qref}", f"#{line}"
    return url + (anchor if line else "")
