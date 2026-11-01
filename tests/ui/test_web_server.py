"""nginx(docker/web/conf/nginx.conf)の配信と、外から見えてはいけないファイル。

静的ファイル、PHPの処理、ソースツリー内の非公開のはずのファイルの扱い。
"""
import pytest

from zbxclient import page_problems


@pytest.mark.parametrize(
    "path,content_type",
    [
        ("assets/styles/blue-theme.css", "text/css"),
        ("js/common.js", "application/javascript"),
        ("jsLoader.php?lang=en_US", "application/javascript"),
    ],
)
def test_static_assets_are_served_with_the_right_type(anonymous, path, content_type):
    resp = anonymous.get(path)

    assert resp.status == 200
    assert resp.content_type in (content_type, "text/javascript")


def test_php_files_run_and_are_never_returned_as_source(anonymous):
    resp = anonymous.get("index.php")

    assert "<?php" not in resp.text


def test_dotfiles_are_denied(anonymous):
    assert anonymous.get(".htaccess").status in (403, 404)


@pytest.mark.parametrize(
    "path",
    [
        "conf/zabbix.conf.php",
        "conf/zabbix.conf.php.example",
        "include/defines.inc.php",
        "app/controllers/CControllerModuleScan.php",
        "vendor/autoload.php",
        "vendor/composer/installed.json",
        "locale/ja/LC_MESSAGES/frontend.po",
        "composer.json",
        "composer.lock",
        "local/conf/",
    ],
)
def test_internal_files_are_not_exposed(anonymous, path):
    """設定・同梱ライブラリの一覧(版が分かる)・コントローラーのソースは、外から取れない/実行できない。

    docker/web/conf/nginx.conf に /app /conf /include /local /locale /vendor と composer.json/lock の
    拒否ルールが無かった間は、composer.json/lock と vendor/composer/installed.json が同梱ライブラリの版を
    丸ごと返し、PHPの内部ファイルは単体で実行されて500や空の200を返していた。
    """
    resp = anonymous.get(path)

    assert resp.status in (403, 404), f"/{path} answered HTTP {resp.status}"


@pytest.mark.parametrize(
    "path",
    [
        "widgets/clock/Widget.php",
        "widgets/clock/actions/WidgetView.php",
        "widgets/clock/views/widget.view.php",
        "widgets/problems/includes/WidgetForm.php",
    ],
)
def test_widget_php_files_are_not_executed_standalone(anonymous, path):
    """ウィジェットのPHP(クラス・アクション・ビュー)は、zabbix.php が中から読むだけで、直接取りに来るものではない。

    nginxのPHP用のlocationが /widgets/<名前>/ 配下のPHPも単体で実行してしまい、本文が空のHTTP 500を返していた
    (app/ や include/ と同じ種類の漏れ。7.0 で widgets/ が増えて顕在化した)。一方 /widgets/*/assets/ は
    ウィジェットのJS/CSSの配信元なので、塞いではいけない(下のテスト)。
    """
    resp = anonymous.get(path)

    assert resp.status == 404, f"/{path} answered HTTP {resp.status}"


@pytest.mark.parametrize("path", ["widgets/clock/assets/js/class.widget.js", "widgets/problems/assets/js/class.widget.js"])
def test_widget_assets_are_still_served(anonymous, path):
    resp = anonymous.get(path)

    assert resp.status == 200
    assert resp.content_type in ("application/javascript", "text/javascript")


@pytest.mark.parametrize("directory", ["local/conf/", "modules/", "widgets/", "widgets/clock/"])
def test_directories_are_not_listed(anonymous, directory):
    assert anonymous.get(directory).status in (403, 404)


def test_the_setup_wizard_is_not_reachable_once_configured(anonymous):
    resp = anonymous.get("setup.php")

    assert "Welcome to" not in resp.visible_text
    assert "Check of pre-requisites" not in resp.visible_text


def test_a_missing_page_is_a_clean_404(anonymous):
    resp = anonymous.get("no-such-page.php")

    assert resp.status == 404
    assert "Fatal error" not in resp.text


def test_a_missing_php_action_does_not_crash(admin):
    resp = admin.get("zabbix.php", params={"action": "no.such.action"})

    assert resp.status in (200, 404)
    assert "Fatal error" not in resp.text and "Stack trace" not in resp.text


@pytest.mark.parametrize("path", ["index_mfa.php", "index_sso.php", "index_http.php", "api_scim.php"])
def test_login_side_entry_points_do_not_crash(anonymous, path):
    """MFA・SSO(SAML)・HTTP認証・SCIM の入口。どれも未設定のまま、ログイン前に叩かれる。

    SAMLはPHPのxml/dom/openssl、SCIMはJSONとAPI層を通る。ここでは「何も設定していないときに、PHPのエラー
    ではなく普通の拒否・転送で返る」ことだけを見る(設定した上での認証はこのスタックの対象外)。
    """
    resp = anonymous.get(path, follow=False)

    # api_scim.php はエンドポイント無しだと、SCIMのエラーJSON(本文のstatusが500)を返す。これは上流の仕様で、
    # PHPのエラーではない。
    scim_error = resp.content_type == "application/json" and "urn:ietf:params:scim:api:messages:2.0:Error" in resp.text
    assert resp.status < 500 or scim_error, f"/{path} answered HTTP {resp.status}: {resp.visible_text[:200]}"
    assert "Fatal error" not in resp.text and "Stack trace" not in resp.text
