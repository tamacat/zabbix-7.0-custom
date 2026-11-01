"""管理画面の主要ページが、PHPのエラーもZabbixのエラー枠も出さずに表示できる。

各ページはPHPの別々の拡張(gd・mbstring・bcmath・xml・gettext・sockets・mysqli)とフロントエンド
同梱ライブラリを通る。PHPを差し替えたり、ui/vendor/ のライブラリを上げたりしたとき、SCAは通っても
特定のページだけが壊れる、ということが起こる(symfony/yamlの件がそうだった)。ここで広く浅く掃く。
"""
import json

import pytest

from zbxclient import page_problems

# (ページ, <title>に含まれるはずの文字列)
LIST_AND_SETTINGS_PAGES = [
    # 監視
    # dashboard.view だけだとダッシュボード一覧へ転送される(最後に開いたダッシュボードが無いとき)ので、IDを指定する。
    ("zabbix.php?action=dashboard.view&dashboardid=1", "Dashboard"),
    ("zabbix.php?action=dashboard.list", "Dashboards"),
    ("zabbix.php?action=problem.view", "Problems"),
    ("zabbix.php?action=host.view", "Hosts"),
    ("zabbix.php?action=latest.view", "Latest data"),
    ("zabbix.php?action=charts.view", "Custom graphs"),
    ("zabbix.php?action=map.view", "Configuration of network maps"),
    ("zabbix.php?action=discovery.view", "Status of discovery"),
    # サービス
    ("zabbix.php?action=service.list", "Services"),
    ("zabbix.php?action=sla.list", "SLA"),
    ("zabbix.php?action=slareport.list", "SLA report"),
    # インベントリ
    ("hostinventoriesoverview.php", "Host inventory overview"),
    ("hostinventories.php", "Host inventory"),
    # レポート
    ("zabbix.php?action=report.status", "System information"),
    ("zabbix.php?action=scheduledreport.list", "Scheduled reports"),
    ("report2.php", "Availability report"),
    ("zabbix.php?action=toptriggers.list", "Top 100 triggers"),
    ("zabbix.php?action=auditlog.list", "Audit log"),
    ("zabbix.php?action=actionlog.list", "Action log"),
    ("report4.php", "Notification report"),
    # データ収集
    ("zabbix.php?action=templategroup.list", "Configuration of template groups"),
    ("zabbix.php?action=hostgroup.list", "Configuration of host groups"),
    ("zabbix.php?action=template.list", "Configuration of templates"),
    ("zabbix.php?action=host.list", "Configuration of hosts"),
    ("zabbix.php?action=maintenance.list", "Configuration of maintenance periods"),
    ("zabbix.php?action=correlation.list", "Event correlation"),
    ("zabbix.php?action=discovery.list", "Configuration of discovery rules"),
    # アラート(アクションは通知元ごとに別の一覧)
    ("zabbix.php?action=action.list&eventsource=0", "Configuration of actions"),
    ("zabbix.php?action=action.list&eventsource=4", "Configuration of actions"),
    ("zabbix.php?action=action.list&eventsource=1", "Configuration of actions"),
    ("zabbix.php?action=action.list&eventsource=2", "Configuration of actions"),
    ("zabbix.php?action=action.list&eventsource=3", "Configuration of actions"),
    ("zabbix.php?action=mediatype.list", "Configuration of media types"),
    ("zabbix.php?action=script.list", "Configuration of scripts"),
    # ユーザー
    ("zabbix.php?action=usergroup.list", "Configuration of user groups"),
    ("zabbix.php?action=userrole.list", "Configuration of user roles"),
    ("zabbix.php?action=user.list", "Configuration of users"),
    ("zabbix.php?action=token.list", "API tokens"),
    ("zabbix.php?action=authentication.edit", "Configuration of authentication"),
    # 管理
    ("zabbix.php?action=gui.edit", "GUI"),
    ("zabbix.php?action=autoreg.edit", "Autoregistration"),
    ("zabbix.php?action=timeouts.edit", "Configuration of timeouts"),
    ("zabbix.php?action=image.list", "Configuration of images"),
    ("zabbix.php?action=iconmap.list", "Configuration of icon mapping"),
    ("zabbix.php?action=regex.list", "Configuration of regular expressions"),
    ("zabbix.php?action=trigdisplay.edit", "Configuration of trigger displaying options"),
    ("zabbix.php?action=geomaps.edit", "Geographical maps"),
    ("zabbix.php?action=module.list", "Modules"),
    ("zabbix.php?action=connector.list", "Connectors"),
    ("zabbix.php?action=miscconfig.edit", "Other configuration parameters"),
    ("zabbix.php?action=audit.settings.edit", "Configuration of audit log"),
    ("zabbix.php?action=housekeeping.edit", "Configuration of housekeeping"),
    ("zabbix.php?action=proxygroup.list", "Configuration of proxy groups"),
    ("zabbix.php?action=proxy.list", "Configuration of proxies"),
    ("zabbix.php?action=macros.edit", "Configuration of macros"),
    ("zabbix.php?action=queue.overview", "Queue"),
    ("zabbix.php?action=queue.overview.proxy", "Queue"),
    ("zabbix.php?action=queue.details", "Queue"),
    # ユーザー設定
    ("zabbix.php?action=userprofile.edit", "User profile"),
    ("zabbix.php?action=user.token.list", "API tokens"),
]


@pytest.mark.parametrize("page,title", LIST_AND_SETTINGS_PAGES, ids=[p for p, _ in LIST_AND_SETTINGS_PAGES])
def test_page_renders_cleanly(admin, page, title):
    resp = admin.get(page)

    assert page_problems(resp) == []
    assert title in resp.title


def test_the_footer_shows_the_7_0_version(admin):
    resp = admin.get("zabbix.php", params={"action": "dashboard.list"})

    assert "Zabbix 7.0." in resp.visible_text


# -- 実データのある画面 ----------------------------------------------------------------------
# conftest.py の seed が作ったホスト・テンプレート・アイテム・トリガー・グラフを、一覧と編集フォームで開く。


def test_the_host_list_shows_the_seeded_host(admin, seed):
    resp = admin.get("zabbix.php", params={"action": "host.list", "filter_name": seed.prefix, "filter_set": "1"})

    assert page_problems(resp) == []
    assert f"{seed.prefix} host" in resp.text


def test_the_template_list_shows_the_seeded_template(admin, seed):
    resp = admin.get("zabbix.php", params={"action": "template.list", "filter_name": seed.prefix, "filter_set": "1"})

    assert page_problems(resp) == []
    assert f"{seed.prefix} template" in resp.text


def test_the_host_group_form_opens(admin, seed):
    resp = admin.get("zabbix.php", params={"action": "hostgroup.edit", "groupid": seed.groupid})

    assert page_problems(resp) == []
    assert f"{seed.prefix} group" in resp.text


def test_the_template_group_form_opens(admin, seed):
    resp = admin.get("zabbix.php", params={"action": "templategroup.edit", "groupid": seed.templategroupid})

    assert page_problems(resp) == []
    assert f"{seed.prefix} template group" in resp.text


@pytest.mark.parametrize(
    "page,params,expected",
    [
        ("zabbix.php", {"action": "item.list", "context": "host", "filter_hostids[]": "{hostid}", "filter_set": "1"}, "CPU load"),
        ("zabbix.php", {"action": "item.edit", "context": "host", "itemid": "{itemid}"}, "zbx7ui.cpu"),
        (
            "zabbix.php",
            {"action": "trigger.list", "context": "host", "filter_hostids[]": "{hostid}", "filter_set": "1"},
            "CPU load is too high",
        ),
        ("zabbix.php", {"action": "trigger.edit", "context": "host", "triggerid": "{triggerid}"}, "CPU load is too high"),
        ("graphs.php", {"context": "host", "filter_hostids[]": "{hostid}", "filter_set": "1"}, "CPU load graph"),
        ("graphs.php", {"context": "host", "form": "update", "graphid": "{graphid}"}, "CPU load graph"),
    ],
    ids=["items-list", "item-form", "triggers-list", "trigger-form", "graphs-list", "graph-form"],
)
def test_configuration_pages_show_the_seeded_entity(admin, seed, page, params, expected):
    values = {"hostid": seed.hostid, "itemid": seed.itemid, "triggerid": seed.triggerid, "graphid": seed.graphid}
    params = {k: v.format(**values) for k, v in params.items()}

    resp = admin.get(page, params=params)

    assert page_problems(resp) == []
    assert expected in resp.text


def test_the_host_edit_form_opens(admin, seed):
    resp = admin.get("zabbix.php", params={"action": "host.edit", "hostid": seed.hostid})

    assert page_problems(resp) == []
    assert seed.host_host in resp.text


def test_the_map_editor_opens(admin, seed):
    resp = admin.get("sysmap.php", params={"sysmapid": seed.sysmapid})

    assert page_problems(resp) == []
    assert f"{seed.prefix} map" in resp.text


def test_the_map_view_opens(admin, seed):
    resp = admin.get("zabbix.php", params={"action": "map.view", "sysmapid": seed.sysmapid})

    assert page_problems(resp) == []
    assert f"{seed.prefix} map" in resp.text


def test_the_graph_view_lists_the_seeded_graph(admin, seed):
    """グラフ画面はグラフの一覧をJSON(charts.view.json)で取り、画像(chart2.php)を並べる。"""
    resp = admin.get(
        "zabbix.php",
        params={"action": "charts.view.json", "filter_hostids[]": seed.hostid, "filter_show": "1", "filter_set": "1"},
    )

    assert resp.status == 200 and resp.content_type == "application/json"
    graphs = json.loads(resp.body)["charts"]
    assert [chart["graphid"] for chart in graphs] == [seed.graphid]
    assert graphs[0]["src"] == "chart2.php"
