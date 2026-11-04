#!/usr/bin/env python3
"""Kimsweb Backend API (speedtest, konversi file, kompresi file, cek keamanan website, geolocation, IP lookup & Kimsbola API-Football v3)"""

import argparse, csv, io, json, os, re, shutil, socket, ssl, subprocess, tempfile, time, urllib.error, urllib.parse, urllib.request, zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent
HAS_FFMPEG = shutil.which("ffmpeg") is not None
ANSI = re.compile(r"\x1b\[[0-9;]*m")
MB = 1 << 20
ZERO_BLOCK = b"\x00" * (64 * 1024)

# Konfigurasi Deteksi Phishing & Keamanan Web
PHISHING_KEYWORDS = [
    "login", "signin", "verify", "verification", "secure", "account", "update", "banking",
    "wallet", "password", "credential", "bca", "bri", "mandiri", "garena", "tokopedia",
    "shopee", "paypal", "facebook-login", "instagram-verify"
]
SUSPICIOUS_TLDS = [".tk", ".ml", ".ga", ".cf", ".gq", ".top", ".xyz", ".work", ".click", ".link", ".zip", ".mov"]
URL_SHORTENERS = ["bit.ly", "tinyurl.com", "t.co", "is.gd", "buff.ly", "cutt.ly", "s.id", "rb.gy"]

# Konfigurasi Kimsbola (API-Football v3 / API-Sports)
API_FOOTBALL_HOST = "v3.football.api-sports.io"
API_FOOTBALL_URL = f"https://{API_FOOTBALL_HOST}"
FOOTBALL_KEY = os.environ.get("FOOTBALL_DATA_KEY", "").strip()
FOOTBALL_CACHE = {}

COMPS_MAP = {
    "PL": 39,     # Premier League
    "PD": 140,    # La Liga
    "BL1": 78,    # Bundesliga
    "SA": 135,    # Serie A
    "FL1": 61,    # Ligue 1
    "CL": 2,      # UEFA Champions League
    "DED": 88,    # Eredivisie
    "PPL": 94,    # Primeira Liga
    "ELC": 40     # Championship
}

HEADERS_BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


class ApiError(Exception):
    def __init__(self, msg, code=502):
        super().__init__(msg)
        self.code = code


def friendly_error(exc: Exception) -> str:
    raw = ANSI.sub("", str(exc)).strip()
    raw = re.sub(r"^ERROR:\s*", "", raw)
    first = raw.splitlines()[0] if raw else "Terjadi kesalahan."
    return first[:300]


def get_current_season():
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def call_api_sports(path: str, ttl: int = 300):
    now = time.time()
    hit = FOOTBALL_CACHE.get(path)
    if hit and now - hit[0] < ttl:
        return hit[1]
    if not FOOTBALL_KEY:
        raise ApiError("API key belum diatur.", 503)

    headers = {
        "x-apisports-key": FOOTBALL_KEY,
        "x-rapidapi-key": FOOTBALL_KEY,
        "x-rapidapi-host": API_FOOTBALL_HOST,
    }
    req = urllib.request.Request(f"{API_FOOTBALL_URL}{path}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        if hit:
            return hit[1]
        msg = {403: "API Key tidak valid.", 429: "Batas permintaan harian tercapai."}.get(e.code, f"HTTP Error {e.code}")
        raise ApiError(msg, e.code if e.code in (403, 429) else 502)
    except Exception:
        if hit:
            return hit[1]
        raise ApiError("Gagal terhubung ke API Sepak Bola.")

    if data.get("errors"):
        err_msg = str(data["errors"])
        if "rateLimit" in err_msg or "requests" in err_msg:
            if hit:
                return hit[1]
            raise ApiError("Batas kuota harian API tercapai.", 429)
        raise ApiError(f"API Error: {err_msg}")

    result = data.get("response", [])
    FOOTBALL_CACHE[path] = (now, result)
    return result


def standings(c_code):
    league_id = COMPS_MAP.get(c_code)
    season = get_current_season()
    res = call_api_sports(f"/standings?league={league_id}&season={season}", ttl=600)
    tables = []
    if res and len(res) > 0:
        league_data = res[0].get("league", {})
        standings_list = league_data.get("standings", [])
        for st in standings_list:
            if not st:
                continue
            rows = []
            for item in st:
                team = item.get("team", {})
                all_s = item.get("all", {})
                goals_s = all_s.get("goals", {})
                rows.append({
                    "pos": item.get("rank"),
                    "team": team.get("name"),
                    "crest": team.get("logo"),
                    "p": all_s.get("played"),
                    "w": all_s.get("win"),
                    "d": all_s.get("draw"),
                    "l": all_s.get("lose"),
                    "gf": goals_s.get("for"),
                    "ga": goals_s.get("against"),
                    "gd": item.get("goalsDiff"),
                    "pts": item.get("points"),
                    "form": item.get("form") or ""
                })
            tables.append({"group": st[0].get("group", ""), "table": rows})
    return {"tables": tables}


def matches(c_code, r_type):
    league_id = COMPS_MAP.get(c_code)
    season = get_current_season()
    now_date = datetime.now(timezone.utc).date()
    
    a, b = {"today": (-2, 2), "results": (-30, 0), "upcoming": (0, 30)}[r_type]
    date_from = now_date + timedelta(days=a)
    date_to = now_date + timedelta(days=b)
    
    path = f"/fixtures?league={league_id}&season={season}&from={date_from}&to={date_to}"
    res = call_api_sports(path, ttl=120)
    
    out = []
    for item in res:
        fixture = item.get("fixture", {})
        status = fixture.get("status", {}).get("short")
        
        is_finished = status in ("FT", "AET", "PEN")
        
        if r_type == "results" and not is_finished:
            continue
        if r_type == "upcoming" and is_finished:
            continue
            
        teams = item.get("teams", {})
        goals = item.get("goals", {})
        
        out.append({
            "id": fixture.get("id"),
            "date": fixture.get("date"),
            "status": status,
            "home": {"name": teams.get("home", {}).get("name"), "crest": teams.get("home", {}).get("logo")},
            "away": {"name": teams.get("away", {}).get("name"), "crest": teams.get("away", {}).get("logo")},
            "hs": goals.get("home"),
            "as": goals.get("away")
        })
        
    out.sort(key=lambda x: x["date"] or "", reverse=(r_type == "results"))
    return {"matches": out}


def scorers(c_code):
    league_id = COMPS_MAP.get(c_code)
    season = get_current_season()
    res = call_api_sports(f"/players/topscorers?league={league_id}&season={season}", ttl=1800)
    
    list_scorers = []
    for item in res:
        p = item.get("player", {})
        stats = (item.get("statistics") or [{}])[0]
        t = stats.get("team", {})
        g = stats.get("goals", {})
        
        list_scorers.append({
            "name": p.get("name"),
            "team": t.get("name"),
            "crest": t.get("logo"),
            "goals": g.get("total") or 0,
            "assists": g.get("assists") or 0,
            "pens": (g.get("penalty") or 0),
            "played": stats.get("games", {}).get("appearences") or 0
        })
    return {"scorers": list_scorers}


def match_detail(fixture_id: str):
    if not fixture_id.isdigit():
        raise ValueError("ID pertandingan tidak valid.")
    res = call_api_sports(f"/fixtures?id={fixture_id}", ttl=180)
    if not res:
        raise ApiError("Detail pertandingan tidak ditemukan.", 404)
    return res[0]



def valid_url(value: str) -> bool:
    try:
        parts = urlparse(value)
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def get_ip_location(ip: str) -> dict:
    if not ip or ip == "-":
        return {"country": "-", "region": "-", "city": "-", "isp": "-", "org": "-"}
    try:
        url = f"http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp,org"
        req = urllib.request.Request(url, headers=HEADERS_BROWSER)
        with urllib.request.urlopen(req, timeout=4) as resp:
            data = json.loads(resp.read().decode())
            if data.get("status") == "success":
                return {
                    "country": data.get("country", "-"),
                    "region": data.get("regionName", "-"),
                    "city": data.get("city", "-"),
                    "isp": data.get("isp", "-"),
                    "org": data.get("org", "-")
                }
    except Exception:
        pass
    return {"country": "Terproteksi / Cloud", "region": "-", "city": "-", "isp": "CDN Provider", "org": "-"}


DOMAIN_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")
TRUSTED_DOMAINS = ["google.com", "youtube.com", "facebook.com", "tokopedia.com", "shopee.co.id"]


def host_matches(host: str, domains) -> bool:
    """Cocokkan host persis atau sebagai subdomain, bukan sekadar substring."""
    return any(host == d or host.endswith("." + d) for d in domains)


def check_website(raw_url: str) -> dict:
    original_input = raw_url.strip()
    if not original_input:
        raise ValueError("URL atau domain tidak boleh kosong.")
    target = original_input
    if not re.match(r"^https?://", target, re.IGNORECASE):
        target = "https://" + target
    try:
        parsed = urlparse(target)
        domain = (parsed.hostname or "").lower().rstrip(".")
        path = parsed.path.lower()
    except ValueError:
        raise ValueError("Format URL/domain tidak valid.")

    if not domain or "." not in domain or not (IPV4_RE.match(domain) or DOMAIN_RE.match(domain)):
        raise ValueError("Nama domain tidak valid.")

    checks = []
    score = 100
    try:
        _, _, ipaddrs = socket.gethostbyname_ex(domain)
    except OSError:
        return {
            "raw_input": original_input, "url": target, "domain": domain,
            "primary_ip": "-", "ip_list": [], "reverse_dns": "-",
            "location": {"country": "-", "region": "-", "city": "-", "isp": "-", "org": "-"},
            "score": 0, "status": "err",
            "verdict": "Website Tidak Dapat Dijangkau (DNS Failed)",
            "checks": [{"title": "Koneksi Server", "status": "err", "msg": "DNS gagal menemukan IP server asal domain ini."}],
        }

    ip_list = list(dict.fromkeys(ipaddrs))  # urutan tetap, tidak diacak oleh set()
    primary_ip = ip_list[0]
    try:
        reverse_dns = socket.gethostbyaddr(primary_ip)[0]
    except OSError:
        reverse_dns = "Edge Proxy / CDN Protected"
    checks.append({"title": "IP Server Asal", "status": "ok", "msg": f"Domain terhubung ke IP: {primary_ip}"})

    location_info = get_ip_location(primary_ip)

    if IPV4_RE.match(domain):
        score -= 35
        checks.append({"title": "Peringatan Phishing (IP Direct)", "status": "err", "msg": "Situs menggunakan IP angka langsung tanpa domain resmi."})

    if host_matches(domain, URL_SHORTENERS):
        score -= 20
        checks.append({"title": "URL Shortener Terdeteksi", "status": "warn", "msg": "Tautan disembunyikan menggunakan penyingkat URL."})

    # Kata kunci dicocokkan per token (dipisah non-huruf/angka), agar "bri" tidak cocok di "bribe"
    tokens = set(re.split(r"[^a-z0-9]+", f"{domain} {path}"))
    joined = f"{domain}{path}"
    found_keywords = [kw for kw in PHISHING_KEYWORDS if kw in tokens or ("-" in kw and kw in joined)]
    if found_keywords and not host_matches(domain, TRUSTED_DOMAINS):
        score -= 30
        checks.append({"title": "Indikasi Phishing", "status": "err", "msg": f"Terdeteksi kata kunci sensitif: '{', '.join(found_keywords)}'."})

    if any(domain.endswith(tld) for tld in SUSPICIOUS_TLDS):
        score -= 25
        checks.append({"title": "TLD Berisiko Tinggi", "status": "warn", "msg": "Domain menggunakan ekstensi TLD murah/gratisan."})

    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ssock:
                if ssock.getpeercert():
                    checks.append({"title": "Sertifikat SSL/TLS", "status": "ok", "msg": "Sertifikat SSL terenkripsi aktif dan valid."})
    except (OSError, ssl.SSLError):
        score -= 30
        checks.append({"title": "Sertifikat SSL/TLS", "status": "err", "msg": "Situs tidak memiliki HTTPS/SSL yang valid."})

    score = max(0, min(100, score))
    verdict = "✅ WEBSITE AMAN & TERVERIFIKASI" if score >= 80 else "⚠️ BERPOTENSI PHISHING / MALWARE" if score < 40 else "⚡ WASPADA / RISIKO SEDANG"
    status_code = "ok" if score >= 80 else "err" if score < 40 else "warn"

    return {
        "raw_input": original_input, "url": target, "domain": domain,
        "primary_ip": primary_ip, "ip_list": ip_list, "reverse_dns": reverse_dns,
        "location": location_info, "score": score, "status": status_code,
        "verdict": verdict, "checks": checks,
    }



def convert(data: bytes, name: str, to: str) -> bytes:
    ext = Path(name).suffix.lower().lstrip(".")
    to = to.lower()
    if ext in ("csv", "json") and to in ("csv", "json") and ext != to:
        text = data.decode("utf-8-sig")
        if ext == "csv":
            return json.dumps(list(csv.DictReader(io.StringIO(text))), ensure_ascii=False, indent=2).encode()
        rows = json.loads(text)
        if isinstance(rows, dict):
            rows = [rows]
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(dict.fromkeys(k for r in rows for k in r)))
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue().encode()
    tmp = tempfile.mkdtemp()
    try:
        src, out = Path(tmp) / f"in.{ext}", Path(tmp) / f"out.{to}"
        if ext in {"png", "jpg", "jpeg", "webp", "bmp"} and to in {"png", "jpg", "jpeg", "webp", "bmp"}:
            from PIL import Image
            src.write_bytes(data)
            im = Image.open(src)
            if to in ("jpg", "jpeg") and im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(out)
        elif HAS_FFMPEG:
            src.write_bytes(data)
            subprocess.run(["ffmpeg", "-y", "-i", str(src), str(out)], check=True, capture_output=True, timeout=900)
        else:
            raise ValueError("Kombinasi konversi format ini tidak didukung.")
        return out.read_bytes()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def compress_file(data: bytes, name: str, quality: int = 70, mode: str = "auto") -> tuple[bytes, str]:
    ext = Path(name).suffix.lower().lstrip(".")
    stem = Path(name).stem
    
    if mode != "zip" and ext in ("jpg", "jpeg", "png", "webp", "bmp"):
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            out = io.BytesIO()
            out_ext = ext if ext != "bmp" else "jpg"
            
            if out_ext in ("jpg", "jpeg"):
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(out, format="JPEG", quality=quality, optimize=True)
            elif out_ext == "webp":
                im.save(out, format="WEBP", quality=quality, optimize=True)
            elif out_ext == "png":
                colors_cnt = min(256, max(32, int(256 * (quality / 100))))
                im = im.convert("P", palette=Image.ADAPTIVE, colors=colors_cnt)
                im.save(out, format="PNG", optimize=True)
            else:
                im.save(out, format=im.format or "JPEG", quality=quality)
                
            res = out.getvalue()
            if len(res) < len(data):
                return res, f"compressed_{stem}.{out_ext}"
        except Exception:
            pass

    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr(name, data)
    return out.getvalue(), f"{stem}_compressed.zip"


ALLOWED_PORTS = {21: "FTP", 22: "SSH", 25: "SMTP", 80: "HTTP", 443: "HTTPS", 3306: "MySQL", 8080: "HTTP Alt", 8443: "HTTPS Alt"}


def port_check(host: str) -> dict:
    host = host.strip().lower().rstrip(".")
    if not (IPV4_RE.match(host) or DOMAIN_RE.match(host)):
        raise ValueError("Domain atau IP tidak valid.")
    try:
        ip = socket.gethostbyname(host)
    except OSError:
        raise ValueError("Domain tidak dapat di-resolve ke IP.")

    def probe(port):
        try:
            with socket.create_connection((ip, port), timeout=1.5):
                return True
        except OSError:
            return False

    ports = list(ALLOWED_PORTS)
    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(probe, ports))
    return {
        "host": host,
        "ip": ip,
        "ports": [{"port": p, "service": ALLOWED_PORTS[p], "open": o} for p, o in zip(ports, results)],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "Kimsweb"

    def log_message(self, *args): pass

    def _send(self, code: int, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > 1 * MB:
            raise ValueError("Permintaan terlalu besar.")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw or b"{}")
        return data if isinstance(data, dict) else {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query)

        if path == "/":
            html_path = ROOT / "index.html"
            if not html_path.exists():
                return self._send(404, {"error": "File index.html tidak ditemukan."})
            return self._send(200, html_path.read_bytes(), "text/html; charset=utf-8")

        if path == "/api/ping":
            return self._send(200, {"ok": 1})

        if path == "/api/speed-down":
            try:
                mb = int(query.get("mb", ["10"])[0])
            except ValueError:
                mb = 10
            total_bytes = min(max(mb, 1), 50) * MB
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(total_bytes))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                written = 0
                while written < total_bytes:
                    to_write = min(len(ZERO_BLOCK), total_bytes - written)
                    self.wfile.write(ZERO_BLOCK[:to_write])
                    written += to_write
            except Exception:
                pass
            return

        try:
            if path == "/api/match-detail":
                return self._send(200, match_detail(query.get("id", [""])[0]))
            if path == "/api/port-check":
                return self._send(200, port_check(query.get("host", [""])[0]))
            if path in ("/api/standings", "/api/matches", "/api/scorers"):
                c = query.get("c", ["PL"])[0]
                if c not in COMPS_MAP:
                    return self._send(400, {"error": "Kompetisi tidak valid."})
                if path == "/api/standings":
                    return self._send(200, standings(c))
                if path == "/api/scorers":
                    return self._send(200, scorers(c))
                r = query.get("r", ["today"])[0]
                if r not in ("today", "results", "upcoming"):
                    return self._send(400, {"error": "Jenis jadwal tidak valid."})
                return self._send(200, matches(c, r))
        except ApiError as e:
            return self._send(e.code, {"error": str(e)})
        except ValueError as exc:
            return self._send(400, {"error": friendly_error(exc)})
        except Exception as exc:
            return self._send(500, {"error": f"Server error: {friendly_error(exc)}"})

        self._send(404, {"error": "Tidak ditemukan."})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        q = urllib.parse.parse_qs(parsed.query)
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if path == "/api/speed-up":
                self.rfile.read(min(length, 50 * MB))
                return self._send(200, {"bytes": length})
            if path == "/api/convert":
                if length > 50 * MB:
                    raise ValueError("File terlalu besar (maks 50 MB).")
                out = convert(self.rfile.read(length), q.get("name", [""])[0], q.get("to", [""])[0])
                return self._send(200, out, "application/octet-stream")
            if path == "/api/compress":
                if length > 100 * MB:
                    raise ValueError("File terlalu besar (maks 100 MB).")
                quality = min(max(int(q.get("quality", ["70"])[0]), 1), 100)
                mode = q.get("mode", ["auto"])[0]
                name = q.get("name", ["file"])[0]
                compressed_data, out_name = compress_file(self.rfile.read(length), name, quality, mode)
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", f"attachment; filename*=UTF-8''{urllib.parse.quote(out_name)}")
                self.send_header("X-Original-Size", str(length))
                self.send_header("X-Compressed-Size", str(len(compressed_data)))
                self.send_header("Access-Control-Expose-Headers", "X-Original-Size, X-Compressed-Size, Content-Disposition")
                self.end_headers()
                self.wfile.write(compressed_data)
                return
            body = self._json_body()
            if path == "/api/check-site":
                return self._send(200, check_website(str(body.get("url", "")).strip()))
            self._send(404, {"error": "Tidak ditemukan."})
        except ValueError as exc:
            self._send(400, {"error": friendly_error(exc)})
        except Exception as exc:
            self._send(500, {"error": friendly_error(exc)})


def main():
    global FOOTBALL_KEY
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8765)))
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"),
                        help="Default 127.0.0.1 (hanya lokal). Pakai 0.0.0.0 jika ingin diakses dari jaringan lain.")
    parser.add_argument("--key", default="", help="API Key dashboard.api-football.com")
    args = parser.parse_args()
    if args.key:
        FOOTBALL_KEY = args.key.strip()

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Kimsweb & Kimsbola berjalan di http://{args.host}:{args.port}/")
    if not FOOTBALL_KEY:
        print("CATATAN: API Key API-Football belum diisi (masukkan via --key KODE_KEY).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()


if __name__ == "__main__":
    main()
