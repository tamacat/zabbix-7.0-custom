"""Zabbix 7.0 のWeb管理画面とJSON-RPC APIを、HTTPだけで操作する最小限のクライアント。

標準ライブラリだけで書いてある(ブラウザも追加のパッケージも要らない)。ここで確かめたいのは、この
プロジェクトが手を入れる層 — ソースからビルドしたPHP、同梱PHPライブラリ(ui/vendor/)、nginx、
entrypoint.shが生成する設定、フォント — が画面として動くことで、ブラウザ上のJavaScriptではない。
"""
from __future__ import annotations

import html
import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import Message
from http.cookiejar import CookieJar


@dataclass
class Response:
    status: int
    headers: Message
    body: bytes
    url: str

    @property
    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    @property
    def content_type(self) -> str:
        return self.headers.get_content_type()

    @property
    def title(self) -> str:
        """<title>の中身(Zabbixは「サーバー名: 画面名」にする)。"""
        found = re.search(r"(?s)<title>(.*?)</title>", self.text)
        return html.unescape(found.group(1)).strip() if found else ""

    @property
    def visible_text(self) -> str:
        """HTMLからscript/styleとタグを除いた、画面に出る文字列(空白は1つに畳む)。"""
        text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", self.text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text)


_CSRF_HIDDEN = re.compile(r'<input type="hidden"[^>]*? name="_csrf_token" value="([^"]+)"')
# 同じ画面のJSには別の操作(template)のトークンも埋まっているので、popup.import を開く呼び出しのものだけを取る。
_CSRF_IMPORT_JS = re.compile(r'popup\.import",\s*\{\s*rules_preset:\s*"template",\s*\[CSRF_TOKEN_NAME\]:\s*"([^"]+)"')
_CSRF_MENU = re.compile(r'data-csrf_token="([^"]+)"')
_FORM_REDIRECT = re.compile(r'(?s)<form method="post" action="([^"]+)"[^>]*id="form-data">(.*?)</form>')


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class ZabbixClient:
    """Cookie(セッション)を持つHTTPクライアント。ステータスコードが4xx/5xxでも例外にしない。"""

    def __init__(self, base_url: str, timeout: float = 60):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._jar = CookieJar()
        cookies = urllib.request.HTTPCookieProcessor(self._jar)
        self._follow = urllib.request.build_opener(cookies)
        self._nofollow = urllib.request.build_opener(cookies, _NoRedirect)

    # -- 低レベル ------------------------------------------------------------------------
    def request(self, method: str, path: str, *, params=None, data=None, headers=None, follow: bool = True) -> Response:
        resp = self._send(method, path, params=params, data=data, headers=headers, follow=follow)
        if not follow:
            return resp
        # Zabbixは「メッセージ付きのリダイレクト」を、自動送信されるフォーム(id="form-data")で返す。ブラウザは
        # DOMContentLoadedで送信するので、同じことをする(これを辿らないと、操作の結果の画面に着かない)。
        for _ in range(3):
            form = _FORM_REDIRECT.search(resp.text) if resp.content_type == "text/html" else None
            if not form or 'getElementById("form-data").submit()' not in resp.text:
                break
            fields = {
                html.unescape(name): html.unescape(value)
                for name, value in re.findall(r'<input type="hidden"[^>]*? name="([^"]+)" value="([^"]*)"', form.group(2))
            }
            resp = self._send("POST", html.unescape(form.group(1)), data=fields)
        return resp

    def _send(self, method: str, path: str, *, params=None, data=None, headers=None, follow: bool = True) -> Response:
        url = self.base_url + "/" + path.lstrip("/")
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params, doseq=True)
        body = None
        if data is not None:
            body = data if isinstance(data, bytes) else urllib.parse.urlencode(data, doseq=True).encode()
        req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
        opener = self._follow if follow else self._nofollow
        try:
            with opener.open(req, timeout=self.timeout) as resp:
                return Response(resp.status, resp.headers, resp.read(), resp.url)
        except urllib.error.HTTPError as err:
            with err:
                return Response(err.code, err.headers, err.read(), url)

    def get(self, path: str, **kwargs) -> Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, data=None, **kwargs) -> Response:
        return self.request("POST", path, data=data, **kwargs)

    def cookie(self, name: str):
        return next((c.value for c in self._jar if c.name == name), None)

    # -- 画面 ----------------------------------------------------------------------------
    def login(self, user: str, password: str) -> Response:
        """ログインフォームをPOSTする。成功すると 302 でダッシュボードへ。"""
        return self.post(
            "index.php",
            {"name": user, "password": password, "autologin": "1", "enter": "Sign in"},
            follow=False,
        )

    # -- CSRFトークン ---------------------------------------------------------------------
    # 7.0 のPOSTは、6.0 の sid の代わりに `_csrf_token` を要る。トークンは「セッションの秘密 + アクション名の
    # 最初の区切り(popup. と massupdate. を除く)」から作られるので、操作ごとに別の値で、その操作の画面が
    # 自分で出力したものしか通らない。画面の部品(フォームの隠し項目・JS・メニュー)から、画面と同じ値を取る。
    def form_token(self, path: str, params=None) -> str:
        """画面のフォームにある隠し項目 `_csrf_token`(例: userprofile.edit は userprofile、module.list は module)。"""
        found = _CSRF_HIDDEN.search(self.get(path, params=params).text)
        if not found:
            raise AssertionError(f"{path} {params} did not render a form with a _csrf_token (is the session valid?)")
        return html.unescape(found.group(1))

    def import_token(self) -> str:
        """popup.import に要るトークン(インポートボタンのJSが埋め込む `import`)。テンプレート一覧の画面から取る。"""
        found = _CSRF_IMPORT_JS.search(self.get("zabbix.php", params={"action": "template.list"}).text)
        if not found:
            raise AssertionError("template.list did not embed the import CSRF token (is the session valid?)")
        return html.unescape(found.group(1))

    def logout(self) -> Response:
        """メニューの「Sign out」と同じ: index.php?reconnect=1 へ、メニューが持つトークン付きでPOSTする。"""
        found = _CSRF_MENU.search(self.get("zabbix.php", params={"action": "userprofile.edit"}).text)
        if not found:
            raise AssertionError("the menu has no sign-out token (is the session valid?)")
        return self.post("index.php", {"_csrf_token": html.unescape(found.group(1))}, params={"reconnect": "1"})


class ApiError(Exception):
    def __init__(self, method: str, error: dict):
        self.method = method
        self.code = error.get("code")
        self.error_message = error.get("message", "")
        self.data = error.get("data", "")
        super().__init__(f"{method}: [{self.code}] {self.error_message} {self.data}".strip())


class ZabbixApi:
    """JSON-RPC。7.0 は認証トークンを `Authorization: Bearer` ヘッダーで渡す(本文の auth は非推奨)。"""

    def __init__(self, base_url: str, timeout: float = 60):
        self._client = ZabbixClient(base_url, timeout)
        self._token = None
        self._seq = 0

    def call(self, method: str, params=None, *, auth: bool = True):
        self._seq += 1
        payload = {"jsonrpc": "2.0", "method": method, "params": params if params is not None else {}, "id": self._seq}
        headers = {"Content-Type": "application/json-rpc"}
        if auth and self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        resp = self._client.post("api_jsonrpc.php", json.dumps(payload).encode(), headers=headers)
        if resp.status != 200:
            raise AssertionError(f"{method}: HTTP {resp.status}: {resp.text[:300]}")
        answer = json.loads(resp.body)
        if "error" in answer:
            raise ApiError(method, answer["error"])
        return answer["result"]

    def login(self, user: str, password: str) -> None:
        self._token = self.call("user.login", {"username": user, "password": password}, auth=False)

    def logout(self) -> None:
        if self._token:
            self.call("user.logout", [])
            self._token = None


# PHPが画面に出す実行時エラー(PHPの不具合・拡張の欠落・ライブラリ非互換で出る)と、Zabbixが赤いメッセージ
# 枠(msg-bad)で出すエラー。正常な画面には出ない。
_PHP_ERROR = re.compile(
    r"Fatal error|Parse error|Uncaught \w+|Stack trace:|Call to undefined|Undefined (?:variable|index|array key|property|constant)"
    r'|Class "[^"]+" not found'
    # PHP自身の警告は「Warning: メッセージ in /パス/ファイル.php on line N」の形。画面の説明文の「Warning: …」は拾わない。
    r"|(?:Warning|Deprecated|Notice)(?:</b>)?:\s[^<]{0,300}?\sin\s/\S+\.php\son\sline\s\d+"
)
_MSG_BAD = re.compile(r'(?s)<[^>]+class="[^"]*msg-bad[^"]*"[^>]*>(.*?)</(?:output|div)>')


def page_problems(resp: Response) -> list[str]:
    """画面として壊れている兆候を返す(空なら問題なし)。HTMLでないレスポンスにはステータスだけを見る。"""
    problems = []
    if resp.status != 200:
        problems.append(f"HTTP {resp.status}")
    if resp.content_type != "text/html":
        return problems
    found = _PHP_ERROR.search(resp.text)
    if found:
        start = max(found.start() - 60, 0)
        problems.append(f"PHP error text: ...{resp.text[start:found.end() + 160]!r}")
    for message in _MSG_BAD.findall(resp.text):
        problems.append("error message box: " + re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", message)).strip()[:200])
    return problems


def wait_for_login_page(client: ZabbixClient, timeout: float) -> None:
    """DBのスキーマ投入やphp-fpmの起動を待つ。本物のログインフォームが返るまで(リトライではなく待機)。"""
    deadline = time.monotonic() + timeout
    last = "no response yet"
    while True:
        try:
            resp = client.get("index.php")
            if resp.status == 200 and 'name="password"' in resp.text:
                return
            last = f"HTTP {resp.status}: {resp.visible_text[:200]}"
        except (OSError, http.client.HTTPException) as err:
            last = repr(err)
        if time.monotonic() > deadline:
            raise TimeoutError(f"{client.base_url}/index.php did not serve the login form within {timeout:.0f}s ({last})")
        time.sleep(2)
