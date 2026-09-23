#!/usr/bin/env python3
"""Render the neofetch-style profile card (assets/dark_mode.svg, assets/light_mode.svg).

Stats come from the GitHub GraphQL API when ACCESS_TOKEN is set; otherwise the
last values saved in assets/stats.json are reused so the card never breaks.
"""
import datetime as dt
import json
import os
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
USER = os.environ.get("USER_NAME", "MrGiveItAway-TPK")
CAREER_START = dt.date(2021, 6, 1)  # first engineering role (Extensya)
WIDTH = 60                          # characters in the right-hand column

THEMES = {
    "dark_mode.svg": dict(ascii="ascii_dark.txt", bg="#161b22", text="#c9d1d9", key="#ffa657", value="#a5d6ff", dots="#616e7f"),
    "light_mode.svg": dict(ascii="ascii_light.txt", bg="#f6f8fa", text="#24292f", key="#953800", value="#0a3069", dots="#c2cfde"),
}


def graphql(query, variables):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Authorization": f"bearer {os.environ['ACCESS_TOKEN']}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.load(resp)
    if body.get("errors"):
        raise RuntimeError(body["errors"])
    return body["data"]


def fetch_stats():
    user = graphql(
        """query($login: String!) {
             user(login: $login) {
               createdAt
               followers { totalCount }
               repositoriesContributedTo(includeUserRepositories: false,
                 contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW]) { totalCount }
             }
           }""",
        {"login": USER},
    )["user"]

    repos, stars, cursor = 0, 0, None
    while True:
        page = graphql(
            """query($login: String!, $cursor: String) {
                 user(login: $login) {
                   repositories(ownerAffiliations: OWNER, first: 100, after: $cursor) {
                     totalCount
                     pageInfo { hasNextPage endCursor }
                     nodes { stargazerCount }
                   }
                 }
               }""",
            {"login": USER, "cursor": cursor},
        )["user"]["repositories"]
        repos = page["totalCount"]
        stars += sum(n["stargazerCount"] for n in page["nodes"])
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    commits = contributions = 0
    since = int(user["createdAt"][:4])
    now = dt.datetime.now(dt.timezone.utc)
    for year in range(since, now.year + 1):
        start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
        end = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        cc = graphql(
            """query($login: String!, $from: DateTime!, $to: DateTime!) {
                 user(login: $login) {
                   contributionsCollection(from: $from, to: $to) {
                     totalCommitContributions
                     contributionCalendar { totalContributions }
                   }
                 }
               }""",
            {"login": USER, "from": start.isoformat(), "to": end.isoformat()},
        )["user"]["contributionsCollection"]
        commits += cc["totalCommitContributions"]
        contributions += cc["contributionCalendar"]["totalContributions"]

    return dict(
        repos=repos,
        contributed=user["repositoriesContributedTo"]["totalCount"],
        stars=stars,
        followers=user["followers"]["totalCount"],
        commits=commits,
        contributions=contributions,
        since=since,
    )


def load_stats():
    cache = ASSETS / "stats.json"
    if os.environ.get("ACCESS_TOKEN"):
        try:
            stats = fetch_stats()
            cache.write_text(json.dumps(stats, indent=2) + "\n")
            return stats
        except Exception as exc:  # keep the last good card rather than failing the workflow
            print(f"stats fetch failed, using cache: {exc}")
    return json.loads(cache.read_text())


def uptime(today):
    years = today.year - CAREER_START.year
    months = today.month - CAREER_START.month
    days = today.day - CAREER_START.day
    if days < 0:
        months -= 1
        prev_month_end = today.replace(day=1) - dt.timedelta(days=1)
        days += prev_month_end.day
    if months < 0:
        years -= 1
        months += 12
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"
    return f"{plural(years, 'year')}, {plural(months, 'month')}, {plural(days, 'day')}"


# A row is a list of (text, css class) spans; the renderer pads with dots.
def kv(key, value, width=WIDTH):
    head = f". {key}:"
    gap = width - len(head) - len(value) - 2
    if gap < 1:
        raise ValueError(f"row too long: {key}: {value}")
    return [(". ", "cc"), (f"{key}", "key"), (":", None), (" " + "." * gap + " ", "cc"), (value, "value")]


def kv2(k1, v1, k2, v2):
    left_width = WIDTH // 2 - 1
    return kv(k1, v1, left_width) + [(" | ", None)] + kv(k2, v2, WIDTH - left_width - 3)


def title(text, lead=""):
    return [(lead + text, None), (" " + "—" * (WIDTH - len(lead + text) - 1), None)]


def rows(stats, today):
    n = lambda v: f"{v:,}"
    return [
        title("mbanifawaz@erp"),
        kv("OS", "Ubuntu, Kali, Manjaro, Windows"),
        kv("Uptime", uptime(today)),
        kv("Host", "Syarah - ERP Squad"),
        kv("Kernel", "Senior Software Engineer, ERP Squad Lead"),
        kv("IDE", "VS Code, Visual Studio"),
        [],
        kv("Languages.Programming", "Python, PHP, JavaScript, C#"),
        kv("Languages.Computer", "HTML, CSS, SQL, Jinja, Bash"),
        kv("Languages.Real", "Arabic, English, German"),
        [],
        kv("Frameworks.ERP", "Frappe, ERPNext"),
        kv("Frameworks.Backend", "Laravel, FastAPI, Flask, .NET"),
        kv("Frameworks.Frontend", "Vue.js, React, Angular"),
        kv("DevOps", "Docker, Helm, ArgoCD, AWS, NGINX"),
        [],
        title("Contact", "- "),
        kv("Email", "m.banifawaz@outlook.com"),
        kv("LinkedIn", "munes-bani-fawaz"),
        kv("YouTube", "@munesbanifawaz"),
        [],
        title("GitHub Stats", "- "),
        kv2("Repos", f"{n(stats['repos'])} {{Contrib: {stats['contributed']}}}", "Stars", n(stats["stars"])),
        kv2("Commits", n(stats["commits"]), "Followers", n(stats["followers"])),
        kv2("Contributions", n(stats["contributions"]), "Since", str(stats["since"])),
    ]


def render(theme, ascii_lines, info_rows):
    height = 30 + 20 * max(len(ascii_lines), len(info_rows))
    out = [
        "<?xml version='1.0' encoding='UTF-8'?>",
        f'<svg xmlns="http://www.w3.org/2000/svg" font-family="ConsolasFallback,Consolas,monospace" '
        f'width="985px" height="{height}px" font-size="16px">',
        "<style>",
        "@font-face {src: local('Consolas'), local('Consolas Bold'); font-family: 'ConsolasFallback';"
        " font-display: swap; -webkit-size-adjust: 109%; size-adjust: 109%;}",
        f".key {{fill: {theme['key']};}} .value {{fill: {theme['value']};}} .cc {{fill: {theme['dots']};}}",
        "text, tspan {white-space: pre;}",
        "</style>",
        f'<rect width="985px" height="{height}px" fill="{theme["bg"]}" rx="15"/>',
        f'<text x="15" y="30" fill="{theme["text"]}">',
    ]
    for i, line in enumerate(ascii_lines):
        out.append(f'<tspan x="15" y="{30 + 20 * i}">{escape(line)}</tspan>')
    out.append("</text>")
    out.append(f'<text x="390" y="30" fill="{theme["text"]}">')
    for i, row in enumerate(info_rows):
        spans = "".join(
            f'<tspan class="{cls}">{escape(text)}</tspan>' if cls else escape(text) for text, cls in row
        )
        out.append(f'<tspan x="390" y="{30 + 20 * i}">{spans}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    today = dt.date.today()
    info_rows = rows(load_stats(), today)
    for name, theme in THEMES.items():
        ascii_lines = (ASSETS / theme["ascii"]).read_text().rstrip("\n").split("\n")
        (ASSETS / name).write_text(render(theme, ascii_lines, info_rows))
        print(f"wrote assets/{name}")


if __name__ == "__main__":
    main()
