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
try:
    from zoneinfo import ZoneInfo
    LOCAL_TZ = ZoneInfo("Asia/Amman")
except Exception:  # tzdata missing: Jordan is fixed UTC+3
    LOCAL_TZ = dt.timezone(dt.timedelta(hours=3))

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
               id
               createdAt
               followers { totalCount }
               repositoriesContributedTo(includeUserRepositories: false,
                 contributionTypes: [COMMIT, PULL_REQUEST, REPOSITORY, PULL_REQUEST_REVIEW]) { totalCount }
             }
           }""",
        {"login": USER},
    )["user"]

    own = walk_repos("user", USER, user["id"], "ownerAffiliations: OWNER, ")
    orgs = graphql(
        """query($login: String!) { user(login: $login) { organizations(first: 100) { nodes { login } } } }""",
        {"login": USER},
    )["user"]["organizations"]["nodes"]
    org_repos = [r for org in orgs for r in walk_repos("organization", org["login"], user["id"])]
    home_owners = {USER.lower()} | {org["login"].lower() for org in orgs}

    # Language share across owned + org repos (forks excluded); only totals leave this script.
    # Each repo counts equally (its bytes are normalised to 1), so a few huge repos can't
    # drown out many smaller ones.
    sizes, colors = {}, {}
    for repo in own + org_repos:
        edges = repo["languages"]["edges"]
        repo_bytes = sum(edge["size"] for edge in edges)
        if repo["isFork"] or not repo_bytes:
            continue
        for edge in edges:
            name = edge["node"]["name"]
            sizes[name] = sizes.get(name, 0) + edge["size"] / repo_bytes
            colors[name] = edge["node"]["color"] or "#8b949e"
    total = sum(sizes.values()) or 1
    languages = [
        dict(name=name, color=colors[name], percent=round(100 * size / total, 2))
        for name, size in sorted(sizes.items(), key=lambda kv: -kv[1])
    ]

    # Commits: every commit authored by this account on the default branch of each own/org repo
    # (forks excluded), plus commits credited in other people's repos.
    commits = sum(r["commits"] for r in own + org_repos if not r["isFork"])
    contributions = 0
    active_days = set()  # ISO dates with any activity; only the streak summary is published
    for repo in own + org_repos:
        if not repo["isFork"] and repo["commits"]:
            active_days.update(commit_days(repo["nameWithOwner"], user["id"]))
    since = int(user["createdAt"][:4])
    now = dt.datetime.now(dt.timezone.utc)
    for year in range(since, now.year + 1):
        start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
        end = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
        cc = graphql(
            """query($login: String!, $from: DateTime!, $to: DateTime!) {
                 user(login: $login) {
                   contributionsCollection(from: $from, to: $to) {
                     contributionCalendar { totalContributions weeks { contributionDays { date contributionCount } } }
                     commitContributionsByRepository(maxRepositories: 100) {
                       repository { owner { login } }
                       contributions { totalCount }
                     }
                   }
                 }
               }""",
            {"login": USER, "from": start.isoformat(), "to": end.isoformat()},
        )["user"]["contributionsCollection"]
        commits += sum(
            item["contributions"]["totalCount"]
            for item in cc["commitContributionsByRepository"]
            if item["repository"]["owner"]["login"].lower() not in home_owners
        )
        contributions += cc["contributionCalendar"]["totalContributions"]
        active_days.update(
            day["date"]
            for week in cc["contributionCalendar"]["weeks"]
            for day in week["contributionDays"]
            if day["contributionCount"]
        )

    return dict(
        repos=len(own),
        org_repos=len(org_repos),
        contributed=user["repositoriesContributedTo"]["totalCount"],
        stars=sum(r["stargazerCount"] for r in own + org_repos),
        followers=user["followers"]["totalCount"],
        commits=commits,
        contributions=contributions,
        since=since,
        languages=languages,
        streak=summarise_streak(active_days),
    )


def commit_days(name_with_owner, author_id):
    """Local (Amman) dates of every commit by the author on the repo's default branch."""
    owner, name = name_with_owner.split("/", 1)
    days, cursor = set(), None
    while True:
        history = graphql(
            """query($owner: String!, $name: String!, $author: ID!, $cursor: String) {
                 repository(owner: $owner, name: $name) {
                   defaultBranchRef { target { ... on Commit {
                     history(author: {id: $author}, first: 100, after: $cursor) {
                       pageInfo { hasNextPage endCursor }
                       nodes { authoredDate }
                     }
                   } } }
                 }
               }""",
            {"owner": owner, "name": name, "author": author_id, "cursor": cursor},
        )["repository"]["defaultBranchRef"]["target"]["history"]
        for node in history["nodes"]:
            stamp = dt.datetime.fromisoformat(node["authoredDate"].replace("Z", "+00:00"))
            days.add(stamp.astimezone(LOCAL_TZ).date().isoformat())
        if not history["pageInfo"]["hasNextPage"]:
            return days
        cursor = history["pageInfo"]["endCursor"]


def summarise_streak(active_days):
    days = sorted(dt.date.fromisoformat(d) for d in active_days)
    if not days:
        return None
    longest = (days[0], days[0])
    run_start = days[0]
    for prev, day in zip(days, days[1:]):
        if (day - prev).days != 1:
            run_start = day
        if day - run_start > longest[1] - longest[0]:
            longest = (run_start, day)
    today = dt.datetime.now(LOCAL_TZ).date()
    current = None
    if days[-1] >= today - dt.timedelta(days=1):  # a streak survives until a full day is missed
        index = len(days) - 1
        while index and (days[index] - days[index - 1]).days == 1:
            index -= 1
        current = (days[index], days[-1])
    span = lambda r: dict(days=(r[1] - r[0]).days + 1, start=r[0].isoformat(), end=r[1].isoformat()) if r else None
    return dict(active_days=len(days), first=days[0].isoformat(), current=span(current), longest=span(longest))


def walk_repos(owner_type, login, author_id, filters=""):
    """All repos of a user or organization (private included when the token can see them)."""
    repos, cursor = [], None
    while True:
        page = graphql(
            f"""query($login: String!, $cursor: String, $author: ID!) {{
                 {owner_type}(login: $login) {{
                   repositories({filters}first: 100, after: $cursor) {{
                     pageInfo {{ hasNextPage endCursor }}
                     nodes {{
                       nameWithOwner
                       stargazerCount
                       isFork
                       defaultBranchRef {{ target {{ ... on Commit {{ history(author: {{id: $author}}) {{ totalCount }} }} }} }}
                       languages(first: 20, orderBy: {{field: SIZE, direction: DESC}}) {{
                         edges {{ size node {{ name color }} }}
                       }}
                     }}
                   }}
                 }}
               }}""",
            {"login": login, "cursor": cursor, "author": author_id},
        )[owner_type]["repositories"]
        for node in page["nodes"]:
            ref = node.pop("defaultBranchRef")
            node["commits"] = ref["target"]["history"]["totalCount"] if ref else 0
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return repos
        cursor = page["pageInfo"]["endCursor"]


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
        kv("Portfolio", "mbanifawaz.github.io"),
        kv("Email", "m.banifawaz@outlook.com"),
        kv("LinkedIn", "munes-bani-fawaz"),
        kv("YouTube", "@munesbanifawaz"),
        [],
        title("GitHub Stats", "- "),
        kv2("Repos", n(stats["repos"] + stats.get("org_repos", 0)), "Stars", n(stats["stars"])),
        kv2("Commits", n(stats["commits"]), "Followers", n(stats["followers"])),
        kv2("Contributions", n(stats["contributions"]), "Contributed", n(stats["contributed"])),
    ]


def svg_head(theme, height):
    return [
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
    ]


def render(theme, ascii_lines, info_rows):
    height = 30 + 20 * max(len(ascii_lines), len(info_rows))
    out = svg_head(theme, height) + [f'<text x="15" y="30" fill="{theme["text"]}">']
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


def render_languages(theme, languages, top=11, columns=3, col_width=27):
    shown = languages[:top]
    rest = round(sum(lang["percent"] for lang in languages[top:]), 2)
    if rest:
        shown.append(dict(name="Other", color="#8b949e", percent=rest))
    per_col = -(-len(shown) // columns)
    height = 92 + 24 * per_col
    out = svg_head(theme, height)
    heading = "- Languages (own + org repos, each repo weighted equally) "
    out.append(f'<text x="15" y="30" fill="{theme["text"]}">{escape(heading + "—" * (WIDTH + 38 - len(heading)))}</text>')
    out.append('<clipPath id="bar"><rect x="15" y="46" width="955" height="12" rx="6"/></clipPath>')
    out.append('<g clip-path="url(#bar)">')
    x = 15.0
    for lang in shown:
        w = 955 * lang["percent"] / 100
        out.append(f'<rect x="{x:.2f}" y="46" width="{w + 0.5:.2f}" height="12" fill="{lang["color"]}"/>')
        x += w
    out.append("</g>")
    for i, lang in enumerate(shown):
        col, row = divmod(i, per_col)
        tx, ty = 40 + col * 315, 90 + row * 24
        pct = f'{lang["percent"]:.2f}%'
        gap = max(1, col_width - len(lang["name"]) - len(pct) - 2)
        out.append(f'<circle cx="{tx - 14}" cy="{ty - 5}" r="6" fill="{lang["color"]}"/>')
        out.append(
            f'<text x="{tx}" y="{ty}"><tspan class="key">{escape(lang["name"])}</tspan>'
            f'<tspan class="cc"> {"." * gap} </tspan><tspan class="value">{pct}</tspan></text>'
        )
    out.append("</svg>")
    return "\n".join(out) + "\n"


def render_streak(theme, streak, width=96):
    fmt = lambda iso: dt.date.fromisoformat(iso).strftime("%b %-d, %Y")
    span = lambda r: f'{r["days"]:,} day{"s" if r["days"] != 1 else ""}  ({fmt(r["start"])} - {fmt(r["end"])})'
    lines = [
        kv("Current Streak", span(streak["current"]) if streak["current"] else "0 days", width),
        kv("Longest Streak", span(streak["longest"]), width),
        kv("Active Days", f'{streak["active_days"]:,}  (since {fmt(streak["first"])})', width),
    ]
    heading = "- Streak (own + org commits and all GitHub contributions) "
    height = 30 + 20 * len(lines) + 10
    out = svg_head(theme, height)
    out.append(f'<text x="15" y="30" fill="{theme["text"]}">')
    out.append(f'<tspan x="15" y="30">{escape(heading + "—" * (width - len(heading)))}</tspan>')
    for i, row in enumerate(lines, start=1):
        spans = "".join(f'<tspan class="{cls}">{escape(t)}</tspan>' if cls else escape(t) for t, cls in row)
        out.append(f'<tspan x="15" y="{30 + 20 * i}">{spans}</tspan>')
    out.append("</text>")
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main():
    today = dt.date.today()
    stats = load_stats()
    info_rows = rows(stats, today)
    for name, theme in THEMES.items():
        ascii_lines = (ASSETS / theme["ascii"]).read_text().rstrip("\n").split("\n")
        (ASSETS / name).write_text(render(theme, ascii_lines, info_rows))
        print(f"wrote assets/{name}")
        if stats.get("streak"):
            streak_name = name.replace("_mode", "_streak")
            (ASSETS / streak_name).write_text(render_streak(theme, stats["streak"]))
            print(f"wrote assets/{streak_name}")
        if stats.get("languages"):
            lang_name = name.replace("_mode", "_languages")
            (ASSETS / lang_name).write_text(render_languages(theme, stats["languages"]))
            print(f"wrote assets/{lang_name}")


if __name__ == "__main__":
    main()
