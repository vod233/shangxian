#!/bin/bash
# Bug#5 修复后最终验证
ADMIN="adm_N6utsCVXqZ2N_a3NWZUsvQMctaoJPKAWOcVbthUaRJM"
BASE="http://127.0.0.1:8020/api"
LICENSE="saa_DTFje43GdrtsYwWtax3xi5xQ79HOhT5o"
MA="saam_066a2714863342ad8d3e80cd1f5ac702"
MB="saam_ba645ea850724fbe9a22c18fef7970ac"
UNK="unknown"
DB="/www/wwwroot/CloudSever.lcjx.yun/app/data/credit_server.db"
OK=0; FAIL=0
pass(){ echo "  [PASS] $1"; OK=$((OK+1)); }
fail(){ echo "  [FAIL] $1"; FAIL=$((FAIL+1)); }

echo "=== 上传后已重启服务，先扣回 V3 错误加到 MA 的 5.0 ==="
MA_NOW=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
echo "  当前 MA=$MA_NOW (期望恢复到 992.878)"
sqlite3 $DB "UPDATE license_activations SET balance_credits=balance_credits-5.0 WHERE machine_id='$MA';"
MA_AFTER=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
echo "  扣回后 MA=$MA_AFTER"
[ "$MA_AFTER" = "992.878" ] && pass "MA 恢复到 992.878" || fail "MA 异常: $MA_AFTER"

echo ""
echo "=== V3 [Bug#3+5]: 新机器激活迁移 license 待分配余额 ==="
echo "--- 临时把 unknown 机器设为 inactive 腾出 active 名额 ---"
sqlite3 $DB "UPDATE license_activations SET status='inactive' WHERE machine_id='$UNK' AND license_key='$LICENSE';"
echo "  active 机器数=$(sqlite3 $DB "SELECT count(*) FROM license_activations WHERE license_key='$LICENSE' AND status='active';") (期望=2)"

NEW_MACH="saam_bug5test_$(date +%s)"
echo "--- 给 license 设 5.0 待分配余额，migrated_to_machine=0 ---"
sqlite3 $DB "UPDATE licenses SET balance_credits=5.0, migrated_to_machine=0 WHERE license_key='$LICENSE';"
sqlite3 $DB "SELECT '  license待分配=', round(balance_credits,4), ' migrated=', migrated_to_machine FROM licenses WHERE license_key='$LICENSE';"

echo "--- 新机器 $NEW_MACH 激活 ---"
VERIFY_RESP=$(curl -s -X POST "$BASE/auth/verify" -H "authorization: Bearer $LICENSE" -H "content-type: application/json" -d "{\"machine_id\":\"$NEW_MACH\"}")
NEW_BAL=$(echo "$VERIFY_RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(round(d.get('balance_credits',-1),4))" 2>/dev/null || echo "ERR")
echo "  verify 返回余额=$NEW_BAL (期望=5.0)"

echo "--- 验证迁移结果 ---"
NEW_DB_BAL=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$NEW_MACH';")
LIC_BAL=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM licenses WHERE license_key='$LICENSE';")
LIC_MIG=$(sqlite3 $DB "SELECT migrated_to_machine FROM licenses WHERE license_key='$LICENSE';")
MA_DB_BAL=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
echo "  新机器 DB 余额=$NEW_DB_BAL (期望=5.0)"
echo "  license 余额=$LIC_BAL migrated=$LIC_MIG (期望=0, 1)"
echo "  MA 余额=$MA_DB_BAL (期望=992.878, 不应被抢迁移)"

[ "$NEW_BAL" = "5.0" ] && pass "verify 返回新机器余额 5.0" || fail "verify 返回异常: $NEW_BAL"
[ "$NEW_DB_BAL" = "5.0" ] && pass "DB 新机器余额 5.0" || fail "DB 新机器余额异常: $NEW_DB_BAL"
[ "$LIC_BAL" = "0.0" ] && pass "license 余额已清零" || fail "license 余额异常: $LIC_BAL"
[ "$LIC_MIG" = "1" ] && pass "migrated 已置 1" || fail "migrated 异常: $LIC_MIG"
[ "$MA_DB_BAL" = "992.878" ] && pass "MA 未被抢迁移" || fail "MA 被污染: $MA_DB_BAL"

echo ""
echo "--- V2 回归: 调 MB 不影响 MA ---"
MA_BEFORE=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
curl -s -X POST "$BASE/admin/licenses/$LICENSE/adjust" -H "authorization: Bearer $ADMIN" -H "content-type: application/json" -d "{\"amount\":2.0,\"reason\":\"v2\",\"machine_id\":\"$MB\"}" >/dev/null
MA_AFTER2=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
echo "  MB+2 前后: MA=$MA_BEFORE → $MA_AFTER2 (应不变)"
[ "$MA_BEFORE" = "$MA_AFTER2" ] && pass "调 MB 不影响 MA" || fail "MA 被污染: $MA_BEFORE → $MA_AFTER2"
curl -s -X POST "$BASE/admin/licenses/$LICENSE/adjust" -H "authorization: Bearer $ADMIN" -H "content-type: application/json" -d "{\"amount\":-2.0,\"reason\":\"v2 restore\",\"machine_id\":\"$MB\"}" >/dev/null

echo ""
echo "=== 清理测试数据 ==="
sqlite3 $DB "DELETE FROM license_activations WHERE machine_id LIKE 'saam_bug5test_%';"
sqlite3 $DB "UPDATE license_activations SET status='active' WHERE machine_id='$UNK' AND license_key='$LICENSE';"
sqlite3 $DB "UPDATE licenses SET balance_credits=0, migrated_to_machine=1 WHERE license_key='$LICENSE';"

echo "--- 最终状态 ---"
sqlite3 -header -column $DB "SELECT 'license' AS t, license_key AS id, round(balance_credits,4) AS bal, migrated_to_machine AS mig FROM licenses WHERE license_key='$LICENSE' UNION ALL SELECT 'MA', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$MA' UNION ALL SELECT 'MB', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$MB' UNION ALL SELECT 'UNK', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$UNK';"
echo "  active 机器数=$(sqlite3 $DB "SELECT count(*) FROM license_activations WHERE license_key='$LICENSE' AND status='active';")"

echo ""
echo "================== 结果汇总 =================="
echo "  PASS: $OK"
echo "  FAIL: $FAIL"
[ $FAIL -eq 0 ] && echo "  ✓ 全部通过" || echo "  ✗ 存在失败"
