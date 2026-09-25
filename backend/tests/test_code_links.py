"""Ссылки на строку кода для четырёх типов репозиториев и карточка уязвимости."""

import pytest

from app.models.entity import RepoType
from app.services.code_links import build_code_url, guess_repo_type
from tests.factories import make_entity, make_finding

REPO = "https://git.corp/team/app"


@pytest.mark.parametrize("rtype,commit,expected", [
    (RepoType.gitlab, True, f"{REPO}/-/blob/abc/src/a.py#L7"),
    (RepoType.github, True, f"{REPO}/blob/abc/src/a.py#L7"),
    (RepoType.gitea, True, f"{REPO}/src/commit/abc/src/a.py#L7"),
    (RepoType.gitea, False, f"{REPO}/src/branch/abc/src/a.py#L7"),
    (RepoType.bitbucket, True, f"{REPO}/browse/src/a.py?at=abc#7"),
])
def test_templates(rtype, commit, expected):
    url = build_code_url(
        repo_url=REPO, repo_type=rtype, ref="abc", path="src/a.py", line=7, ref_is_commit=commit
    )
    assert url == expected


def test_prefix_no_line_and_missing_parts():
    url = build_code_url(
        repo_url=REPO + ".git", repo_type=RepoType.gitlab, ref="main", path="./a b.py",
        line=None, ref_is_commit=False, path_prefix="services/api/",
    )
    assert url == f"{REPO}/-/blob/main/services/api/a%20b.py"
    assert build_code_url(
        repo_url=REPO, repo_type=RepoType.gitlab, ref="main",
        path="services/api/x.py", line=1, ref_is_commit=False, path_prefix="services/api",
    ) == f"{REPO}/-/blob/main/services/api/x.py#L1"
    assert build_code_url(
        repo_url=None, repo_type=RepoType.gitlab, ref="a", path="x", line=1, ref_is_commit=True
    ) is None
    assert build_code_url(
        repo_url="https://unknown.host/x", repo_type=None, ref="a", path="x", line=1,
        ref_is_commit=True,
    ) is None


def test_guess_repo_type():
    assert guess_repo_type("https://github.com/o/r") == RepoType.github
    assert guess_repo_type("https://gitlab.corp/o/r") == RepoType.gitlab
    assert guess_repo_type("https://code.corp/o/r") is None


async def test_detail_has_links_and_path(client, admin, db):
    _, h = admin
    parent = await make_entity(
        db, "fintech", repo_url="https://gitlab.corp/fin/app", repo_type=RepoType.gitlab,
        default_branch="main",
    )
    child = await make_entity(db, "api", parent_id=parent.id)
    f = await make_finding(
        db, child, "fp", file_path="src/a.py", line_start=3, commit_sha="c0ffee",
        help_text="Use parameters",
    )
    r = await client.get(f"/api/v1/findings/by-number/{f.number}", headers=h)
    assert r.status_code == 200
    body = r.json()
    assert body["entity_path"] == "fintech/api"
    assert body["entity_name"] == "api"
    assert body["code_url"] == "https://gitlab.corp/fin/app/-/blob/c0ffee/src/a.py#L3"
    assert body["code_url_head"] == "https://gitlab.corp/fin/app/-/blob/main/src/a.py#L3"
    assert body["help_text"] == "Use parameters"


async def test_detail_without_repo_has_no_links(client, admin, db):
    _, h = admin
    e = await make_entity(db, "svc")
    f = await make_finding(db, e, "fp", file_path="a.py", commit_sha="c")
    body = (await client.get(f"/api/v1/findings/{f.id}", headers=h)).json()
    assert body["code_url"] is None
    assert body["code_url_head"] is None
