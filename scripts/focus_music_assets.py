"""Fetch attributed focus audio and create the matching original SVG covers.

Run explicitly with `just focus-music-assets`; normal builds use bundled files.
"""

import hashlib
import html
import json
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "qt/aqt/builtin_features/synapsepro/media/focus"
BLANKET = "9d229d2be7cb6619135d55ff9e49926e40298686"
BY = "https://creativecommons.org/licenses/by/4.0/"
CC0 = "https://creativecommons.org/publicdomain/zero/1.0/"
CATALOG = "https://incompetech.com/music/royalty-free/music.html"

# Filename, published title, ISRC, displayed title, cover, colors.
MUSIC = [
    (
        "gymnopedie",
        "Gymnopedie No 1",
        "USUAN1100787",
        "轻柔钢琴",
        "piano",
        "#c9ddd7",
        "#526f70",
    ),
    (
        "meditation",
        "Meditation Impromptu 01",
        "USUAN1100163",
        "冥想钢琴",
        "meditation",
        "#dbd7ec",
        "#75618c",
    ),
    (
        "dreams",
        "Dreams Become Real",
        "USUAN1500027",
        "梦境氛围",
        "dreams",
        "#acbbdd",
        "#424d80",
    ),
    (
        "clean_soul",
        "Clean Soul",
        "USUAN1300033",
        "柔和电钢琴",
        "electric",
        "#b8d7dc",
        "#43666d",
    ),
    (
        "easy_lemon",
        "Easy Lemon",
        "USUAN1200076",
        "悠闲午后",
        "afternoon",
        "#eadfb6",
        "#a78145",
    ),
    (
        "bossa",
        "Bossa Antigua",
        "USUAN1700069",
        "波萨诺瓦",
        "bossa",
        "#e8c9b0",
        "#936049",
    ),
]
# Local stem, Blanket stem, displayed title, author, editor, source, license, cover, colors.
AMBIENT = [
    (
        "birds",
        "birds",
        "林间鸟鸣",
        "kvgarlic",
        "Porrumentzio",
        "https://freesound.org/people/kvgarlic/sounds/156826/",
        "CC0 1.0",
        CC0,
        "birds",
        "#c3d7a9",
        "#507656",
    ),
    (
        "stream",
        "stream",
        "潺潺溪流",
        "gluckose",
        "",
        "https://freesound.org/people/gluckose/sounds/333987/",
        "CC0 1.0",
        CC0,
        "stream",
        "#b6d9d4",
        "#407d84",
    ),
    (
        "waves",
        "waves",
        "海岸浪声",
        "Luftrum",
        "Porrumentzio",
        "https://freesound.org/people/Luftrum/sounds/48412/",
        "CC BY 4.0",
        BY,
        "waves",
        "#b9d7e5",
        "#477e9e",
    ),
    (
        "coffee_shop",
        "coffee-shop",
        "咖啡馆",
        "stephan",
        "",
        "https://soundbible.com/1664-Restaurant-Ambiance.html",
        "Public Domain",
        "https://soundbible.com/1664-Restaurant-Ambiance.html",
        "cafe",
        "#dfc8af",
        "#936c4e",
    ),
    (
        "fireplace",
        "fireplace",
        "壁炉柴火",
        "ezwa",
        "",
        "https://soundbible.com/1543-Fireplace.html",
        "Public Domain",
        "https://soundbible.com/1543-Fireplace.html",
        "fire",
        "#e2bfa7",
        "#9b604d",
    ),
    (
        "summer_night",
        "summer-night",
        "夏夜虫鸣",
        "Lisa Redfern",
        "",
        "https://soundbible.com/2083-Crickets-Chirping-At-Night.html",
        "Public Domain",
        "https://soundbible.com/2083-Crickets-Chirping-At-Night.html",
        "night",
        "#acbbcd",
        "#475772",
    ),
]

MOTIFS = {
    "piano": '<rect x="48" y="58" width="88" height="70" rx="5" fill="white"/><path d="M66 58v70m18-70v70m18-70v70m18-70v70"/><path stroke-width="10" d="M66 58v38m18-38v38m36-38v38"/>',
    "meditation": '<path d="M92 132C52 106 51 76 61 70c18 3 31 22 31 62Zm0 0c40-26 41-56 31-62-18 3-31 22-31 62Zm0-72c-24 29-24 51 0 72 24-21 24-43 0-72Z"/>',
    "dreams": '<path fill="white" stroke="none" d="M109 52a40 40 0 1 0 13 71 39 39 0 0 1-13-71Z"/><path d="M121 66h16m-8-8v16M50 112h12m-6-6v12"/>',
    "electric": '<path d="M40 98h16l9-25 16 53 15-75 15 62 10-15h24"/>',
    "afternoon": '<circle cx="94" cy="89" r="26" fill="white" stroke="none"/><path d="M43 128h99M94 43v9m0 74v9M47 89h10m74 0h10M61 56l7 7m52 52 7 7m-66 0 7-7m52-52 7-7"/>',
    "bossa": '<path fill="white" d="M103 75c-12-13-28-8-25 9 1 9-23 8-22 26 0 18 29 29 42 17 13-12-6-20 5-27 9-6 14-19 0-25Z"/><path stroke-width="10" d="m94 100 37-48"/><circle cx="88" cy="104" r="9"/>',
    "birds": '<path d="M41 124c38-5 58-20 91-65M86 96c-14-34-31-34-37-24 4 17 17 26 37 24Zm15-14c28 5 39-4 36-16-17-4-28 1-36 16Z"/><path d="M54 47q9-12 18 0 9-12 18 0"/>',
    "stream": '<path d="M89 40c-57 30 72 34 10 63s-11 37 14 48" stroke="white" stroke-width="20"/><path d="m40 90 12-29 14 28Zm75 24 10-18 11 18Z"/>',
    "waves": '<path d="M36 80q14-16 28 0t28 0 28 0 28 0M36 103q14-16 28 0t28 0 28 0 28 0M36 126q14-16 28 0t28 0 28 0 28 0"/>',
    "cafe": '<path fill="white" d="M53 78h69v25c0 36-69 36-69 0Z"/><path d="M123 82h9c21 0 14 26-10 26M48 139h82M73 47q-9 10 0 19m21-19q-9 10 0 19"/>',
    "fire": '<path fill="white" d="M90 44c8 39-24 34-24 61 0 31 54 31 54-1 0-17-14-20-17-32 0 18-17 22-13-28Z"/><path d="m59 145 69-16m-69 0 69 16"/>',
    "night": '<path fill="white" stroke="none" d="M105 43a29 29 0 1 0 13 52 28 28 0 0 1-13-52Z"/><path d="m46 147 6-24 8 24m15 0 9-33 8 33m33 0 8-22 9 22M49 57h8m-4-4v8m71 44h10m-5-5v10"/>',
}


def cover(name, light, dark):
    rings = "".join(f'<circle cx="172" cy="96" r="{r}"/>' for r in range(30, 75, 5))
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="256" height="192" viewBox="0 0 256 192">
<title>{name}</title><circle cx="172" cy="96" r="77" fill="#222426"/>
<g fill="none" stroke="#484b4e" stroke-width=".8">{rings}</g>
<circle cx="172" cy="96" r="22" fill="{light}"/><circle cx="172" cy="96" r="5" fill="#242629"/>
<rect x="23" y="24" width="149" height="149" rx="3" fill="#000" opacity=".15"/>
<rect x="18" y="18" width="150" height="150" rx="3" fill="{light}"/>
<path d="M18 133 168 70v98H18Z" fill="{dark}" opacity=".12"/>
<g fill="none" stroke="{dark}" stroke-width="4" stroke-linecap="round" stroke-linejoin="round">{MOTIFS[name]}</g>
</svg>
'''


def tracks():
    for stem, title, isrc, label, art, light, dark in MUSIC:
        yield {
            "file": f"{stem}.mp3",
            "title": "Gymnopedie No. 1" if stem == "gymnopedie" else title,
            "label": label,
            "author": "Kevin MacLeod",
            "editor": "",
            "license": "CC BY 4.0",
            "license_url": BY,
            "source": f"https://incompetech.com/music/royalty-free/index.html?isrc={isrc}",
            "license_evidence": CATALOG,
            "cover": f"{art}.svg",
            "colors": [light, dark],
            "download": "https://incompetech.com/music/royalty-free/mp3-royaltyfree/"
            + urllib.parse.quote(title + ".mp3"),
            "changes": "Audio copied without modification. Gymnopedie No. 1 composed by Erik Satie."
            if stem == "gymnopedie"
            else "Audio copied without modification.",
        }
    for (
        stem,
        upstream,
        label,
        author,
        editor,
        source,
        lic,
        lic_url,
        art,
        light,
        dark,
    ) in AMBIENT:
        yield {
            "file": f"{stem}.ogg",
            "title": upstream.replace("-", " ").title(),
            "label": label,
            "author": author,
            "editor": editor,
            "license": lic,
            "license_url": lic_url,
            "source": source,
            "license_evidence": f"https://github.com/rafaelmardojai/blanket/blob/{BLANKET}/SOUNDS_LICENSING.md",
            "cover": f"{art}.svg",
            "colors": [light, dark],
            "download": f"https://raw.githubusercontent.com/rafaelmardojai/blanket/{BLANKET}/data/resources/sounds/{upstream}.ogg",
            "changes": "Blanket audio copied without further modification; original loop editor credited separately.",
        }


def fetch(track, expected_hash=None):
    path = DEST / track["file"]
    if not path.exists():
        request = urllib.request.Request(
            track["download"], headers={"User-Agent": "Anki-FocusMusic/1.0"}
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(32 * 1024 * 1024 + 1)
        if not 10_000 < len(data) <= 32 * 1024 * 1024:
            raise ValueError(f"Unexpected audio size: {track['file']}")
        if not (data[:3] == b"ID3" or data[:4] == b"OggS" or data[:1] == b"\xff"):
            raise ValueError(f"Not an audio response: {track['file']}")
        path.write_bytes(data)
    track["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if expected_hash and track["sha256"] != expected_hash:
        raise ValueError(f"Audio differs from the reviewed catalog: {track['file']}")
    track["bytes"] = path.stat().st_size
    (DEST / track["cover"]).write_text(
        cover(Path(track["cover"]).stem, *track.pop("colors")), encoding="utf8"
    )
    print(f"Ready: {track['label']} ({track['bytes']} bytes)", flush=True)
    return track


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = DEST / "catalog.json"
    expected = (
        {
            t["file"]: t["sha256"]
            for t in json.loads(manifest.read_text(encoding="utf8"))
        }
        if manifest.exists()
        else {}
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        catalog = list(
            pool.map(lambda track: fetch(track, expected.get(track["file"])), tracks())
        )
    (DEST / "catalog.json").write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf8"
    )
    rows = []
    for track in catalog:
        t = {key: html.escape(str(value), quote=True) for key, value in track.items()}
        editor = f" · 循环编辑：{t['editor']}" if t["editor"] else ""
        rows.append(
            f"<li><b>{t['label']}</b> / {t['title']}<br>{t['author']}{editor}<br>"
            f'<a href="{t["source"]}">原始来源</a> · <a href="{t["license_url"]}">{t["license"]}</a>'
            f"<br><small>{t['changes']}</small></li>"
        )
    credits = (
        """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head><body>
<h2>新增专注音乐：音源与授权</h2>
<p>这 12 首音频随软件保存，可离线播放。文件保留原始录音，封面为本项目原创 SVG（CC0）。</p>
<p>轻音乐：Kevin MacLeod (incompetech.com)，Licensed under Creative Commons: By Attribution 4.0 License，
<a href="https://creativecommons.org/licenses/by/4.0/">https://creativecommons.org/licenses/by/4.0/</a>。
环境音由 <a href="https://github.com/rafaelmardojai/blanket">Blanket</a> 整理，按以下各自授权使用。
曲目名称采用便于选择的中文标签。</p><ol>
"""
        + "\n".join(rows)
        + "\n</ol><p>原有 6 首音频沿用 SynapsePro 随附资源。</p></body></html>\n"
    )
    (DEST / "CREDITS.html").write_text(credits, encoding="utf8")
    print(
        f"Bundled {len(catalog)} new tracks, {sum(t['bytes'] for t in catalog) / 1024**2:.1f} MiB."
    )


if __name__ == "__main__":
    main()
