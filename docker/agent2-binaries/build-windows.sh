#!/bin/sh
# zabbix_agent2.exe (Windows, 64-bit) を、Linux上のMinGW-w64でクロスコンパイルする。
#
# アップストリームの build/mingw/Makefile は、Windows上のコマンドプロンプトで動かす前提
# (SHELL := cmd、wmic、バックスラッシュのパス)で書かれている。ここでは同じ手順を、同じ
# コンパイルオプション・同じオブジェクトの集合のまま、POSIX shellで再現する。オブジェクトの
# 一覧がアップストリームのMakefileとずれていないことは tests/test_agent2_binaries.py が確認する
# (Zabbixのソースを更新したときに、足りないオブジェクトを見逃さないため)。
#
# 前提(docker/agent2-binaries/Dockerfile が用意する):
#   /build        Zabbixソース(ZABBIX_SRC_DIR の中身)
#   /opt/deps     MinGW向けに静的ビルドしたOpenSSL・PCRE2・libiconv(include/ と lib/)
#   GOTOOLCHAIN   ビルドに使うGoのバージョン(docker/agent2/Dockerfile と同じ値)
# 出力: ${OUT_DIR:-/out}/zabbix_agent2.exe
set -eu

SRC=/build
DEPS=/opt/deps
OUT_DIR="${OUT_DIR:-/out}"
CC=x86_64-w64-mingw32-gcc
WINDRES=x86_64-w64-mingw32-windres
OBJ_DIR="${SRC}/build/mingw/output"
SHIM_INC=/tmp/shim-include
SHIM_LIB=/tmp/shim-lib

cd "${SRC}"
mkdir -p "${OBJ_DIR}" "${OUT_DIR}" "${SHIM_INC}" "${SHIM_LIB}"

# ZabbixのソースはWindowsのヘッダーを、Windowsでの綴り(大文字小文字)のままincludeしている。
# MinGWのヘッダーは小文字のファイル名なので、大文字小文字を区別するLinuxでは見つからない。
# 綴りの違うヘッダーごとに、本物を指す小さな転送用ヘッダーを置く(ソースは書き換えない)。
for header in DbgHelp Iphlpapi Netioapi Wbemidl Winber Winldap Wspiapi; do
	lower="$(echo "${header}" | tr '[:upper:]' '[:lower:]')"
	echo "#include <${lower}.h>" > "${SHIM_INC}/${header}.h"
done
# 同じ理由で、cgoが -lDbghelp / -lWevtapi とリンクを指定するライブラリ(MinGWでは小文字)も合わせる。
ln -sf /usr/x86_64-w64-mingw32/lib/libdbghelp.a "${SHIM_LIB}/libDbghelp.a"
ln -sf /usr/x86_64-w64-mingw32/lib/libwevtapi.a "${SHIM_LIB}/libWevtapi.a"

# -fcommon: include/symbols.h はヘッダーの中で関数ポインタ変数を(externなしで)定義している。
# GCC 10以降の既定(-fno-common)では、それをincludeした複数のオブジェクトで多重定義になる。
# アップストリームが想定している従来の挙動(-fcommon)に戻す。
CFLAGS="-O2 -g -fcommon -DHAVE_STDINT_H=1 -DZBX_BUILD_AGENT2=1 -DHAVE_THREAD_LOCAL=1"
CFLAGS="${CFLAGS} -I${SRC}/build/win32/include/common -I${SRC}/build/mingw -I${SRC}/include -I${SRC}/include/common -I${SHIM_INC}"
# TLS(PSK・証明書)とPCRE2。アップストリームのMakefileの OPENSSL= / PCRE2= の分岐に相当する。
CFLAGS="${CFLAGS} -DHAVE_OPENSSL=1 -DHAVE_OPENSSL_WITH_PSK=1 -DPCRE2_STATIC -DHAVE_PCRE2_H=1 -I${DEPS}/include"

compile() { # compile <出力名> <ソース(src/からの相対)> [追加フラグ...]
	name="$1"
	source="$2"
	shift 2
	echo "CC ${name}"
	# shellcheck disable=SC2086 # CFLAGSは意図的に単語分割する
	${CC} ${CFLAGS} -DUNICODE "$@" -c "${SRC}/src/${source}" -o "${OBJ_DIR}/${name}.o"
}

compile bincommon libs/zbxbincommon/bincommon.c
compile threads libs/zbxthreads/threads.c
compile interval libs/zbxexpr/interval.c
compile num libs/zbxnum/num.c
compile str libs/zbxstr/str.c
compile common_str libs/zbxcommon/common_str.c
compile common_log libs/zbxcommon/common_log.c
compile components_strings_representations libs/zbxcommon/components_strings_representations.c
compile libc_wrappers libs/zbxcommon/libc_wrappers.c
compile param libs/zbxparam/param.c
compile misc libs/zbxcommon/misc.c
compile time libs/zbxtime/time.c
compile expr libs/zbxexpr/expr.c
compile host libs/zbxexpr/host.c
compile macro libs/zbxexpr/macro.c
compile function libs/zbxexpr/function.c
compile token libs/zbxexpr/token.c
compile fatal libs/zbxwin32/fatal.c
compile disk libs/zbxwin32/disk.c
compile ip libs/zbxip/ip.c
compile iprange libs/zbxip/iprange.c
compile zbxhash libs/zbxhash/zbxhash.c
compile md5 libs/zbxhash/md5.c
compile sysinfo libs/zbxsysinfo/sysinfo.c -DWITH_COMMON_METRICS
compile vector libs/zbxalgo/vector.c
compile hashset libs/zbxalgo/hashset.c
compile zbxregexp libs/zbxregexp/zbxregexp.c
compile persistent_state zabbix_agent/logfiles/persistent_state.c
compile logfiles zabbix_agent/logfiles/logfiles.c
compile file libs/zbxfile/file.c
compile algodefs libs/zbxalgo/algodefs.c
compile json libs/zbxjson/json.c -DWITH_COMMON_METRICS
compile json_parser libs/zbxjson/json_parser.c -DWITH_COMMON_METRICS
compile jsonpath libs/zbxjson/jsonpath.c -DWITH_COMMON_METRICS
compile jsonobj libs/zbxjson/jsonobj.c -DWITH_COMMON_METRICS
compile sha256crypt libs/zbxhash/sha256crypt.c -DWITH_COMMON_METRICS
compile variant libs/zbxvariant/variant.c -DWITH_COMMON_METRICS
compile sysinfo_system libs/zbxsysinfo/common/system.c
compile sysinfo_dns libs/zbxsysinfo/common/dns.c
compile sysinfo_ip_reverse libs/zbxsysinfo/common/ip_reverse.c
compile sysinfo_vfs_file libs/zbxsysinfo/common/vfs_file.c
compile sysinfo_dir libs/zbxsysinfo/common/dir.c
compile sysinfo_alias libs/zbxsysinfo/alias/alias.c
compile eventlog zabbix_agent/active_checks/eventlog_win32/eventlog.c
compile process_eventslog zabbix_agent/active_checks/eventlog_win32/process_eventslog.c
compile process_eventslog6 zabbix_agent/active_checks/eventlog_win32/process_eventslog6.c
compile symbols libs/zbxwin32/symbols.c
compile win32_file libs/zbxfile/win32/win32_file.c
compile tls_version libs/zbxcomms/tls_version.c

# バージョン情報・アイコン等のWindowsリソース。resource.rc とそこからincludeされるファイルは
# Windowsのパス区切り(\)でincludeを書いているので、Linuxで読めるよう / に直してから使う。
sed -i -E '/#[[:space:]]*include/ s#\\#/#g' "${SRC}"/build/win32/project/*.h "${SRC}"/build/win32/project/*.rc
echo "WINDRES resource.syso"
${WINDRES} "${SRC}/build/win32/project/resource.rc" --input-format=rc -O coff --target=pe-x86-64 \
	-D _WINDOWS -D ZABBIX_AGENT2 -o "${SRC}/src/go/cmd/zabbix_agent2/resource.syso"

PKG=golang.zabbix.com/agent2/pkg/version
GOLDFLAGS="-X ${PKG}.compileOs=windows -X ${PKG}.compileArch=amd64"
GOLDFLAGS="${GOLDFLAGS} -X ${PKG}.compileDate=$(date -u +%Y-%m-%d) -X ${PKG}.compileTime=$(date -u +%H:%M:%S)"
GOLDFLAGS="${GOLDFLAGS} -X main.confDefault=zabbix_agent2.win.conf -X main.applicationName=zabbix_agent2"
# -extldflags: -static でCランタイム・OpenSSL・PCRE2・libiconvをexeに取り込む(DLLの同梱が要らなくなる)。
# OpenSSLが使うWindowsのシステムライブラリ(crypt32等)は、libcrypto.a より後ろに置かないと
# 解決されないため、他のリンクオプションの最後に付く -extldflags に置く。
GOLDFLAGS="${GOLDFLAGS} -extldflags '-static -lcrypt32 -lgdi32 -luser32 -ladvapi32 -lws2_32'"

echo "GO BUILD"
cd "${SRC}/src/go"
GOOS=windows GOARCH=amd64 CGO_ENABLED=1 CC="${CC}" \
	CGO_CFLAGS="${CFLAGS}" CGO_LDFLAGS="-L${DEPS}/lib -L${SHIM_LIB}" \
	go build -tags "openssl pcre2" -ldflags="${GOLDFLAGS}" \
	-o "${OUT_DIR}/zabbix_agent2.exe" golang.zabbix.com/agent2/cmd/zabbix_agent2

ls -l "${OUT_DIR}/zabbix_agent2.exe"
