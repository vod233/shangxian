# DEPRECATED: PostgreSQL migration complete. Use psql instead.
# Original script follows:
#!/bin/bash
# 重新设计的验证脚本：避免 MAX_MACHINES_PER_LICENSE 限制
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

echo "=== 重启服务加载新代码 ==="
systemctl restart social-ai-credit.service
sleep 2
systemctl is-active social-ai-credit.service && pass "服务启动" || fail "服务未启动"

echo ""
echo "=== 回归 V1: verify 返回各自机器余额 ==="
MA_BAL=$(curl -s -X POST "$BASE/auth/verify" -H "authorization: Bearer $LICENSE" -H "content-type: application/json" -d "{\"machine_id\":\"$MA\"}" | python3 -c "import sys,json;d=json.load(sys.stdin);print(round(d['balance_credits'],4))")
MB_BAL=$(curl -s -X POST "$BASE/auth/verify" -H "authorization: Bearer $LICENSE" -H "content-type: application/json" -d "{\"machine_id\":\"$MB\"}" | python3 -c "import sys,json;d=json.load(sys.stdin);print(round(d['balance_credits'],4))")
echo "  verify: MA=$MA_BAL (期望≈992.878) MB=$MB_BAL (期望=0.0)"
[ "$(echo "$MA_BAL > 990" | bc)" = "1" ] && pass "MA余额正确" || fail "MA余额异常: $MA_BAL"
[ "$(echo "$MB_BAL == 0" | bc)" = "1" ] && pass "MB余额正确" || fail "MB余额异常: $MB_BAL"

echo ""
echo "=== V3 [Bug#3]: 新机器激活迁移 license 待分配余额 ==="
echo "--- 临时把 unknown 机器设为 inactive 腾出 active 名额 ---"
sqlite3 $DB "UPDATE license_activations SET status='inactive' WHERE machine_id='$UNK' AND license_key='$LICENSE';"
ACTIVE_CNT=$(sqlite3 $DB "SELECT count(*) FROM license_activations WHERE license_key='$LICENSE' AND status='active';")
echo "  当前 active 机器数=$ACTIVE_CNT (期望=2)"

NEW_MACH="saam_bug3test_$(date +%s)"
echo "--- 给 license 设 5.0 待分配余额，migrated_to_machine=0 ---"
sqlite3 $DB "UPDATE licenses SET balance_credits=5.0, migrated_to_machine=0 WHERE license_key='$LICENSE';"
sqlite3 $DB "SELECT '  license待分配=', round(balance_credits,4), ' migrated=', migrated_to_machine FROM licenses WHERE license_key='$LICENSE';"

echo "--- 新机器 $NEW_MACH 激活 ---"
VERIFY_RESP=$(curl -s -X POST "$BASE/auth/verify" -H "authorization: Bearer $LICENSE" -H "content-type: application/json" -d "{\"machine_id\":\"$NEW_MACH\"}")
echo "  verify 响应: $VERIFY_RESP" | head -c 300
echo ""
NEW_BAL=$(echo "$VERIFY_RESP" | python3 -c "import sys,json;d=json.load(sys.stdin);print(round(d.get('balance_credits',-1),4))" 2>/dev/null || echo "ERR")
echo "  新机器 verify 返回余额=$NEW_BAL (期望=5.0)"

echo "--- 验证迁移结果 ---"
sqlite3 $DB "SELECT '  新机器余额=', round(balance_credits,4) FROM license_activations WHERE machine_id='$NEW_MACH';"
LIC_BAL=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM licenses WHERE license_key='$LICENSE';")
LIC_MIG=$(sqlite3 $DB "SELECT migrated_to_machine FROM licenses WHERE license_key='$LICENSE';")
echo "  license余额=$LIC_BAL migrated=$LIC_MIG (期望=0, 1)"

# 判定
[ "$NEW_BAL" = "5.0" ] && pass "新机器获得迁移余额 5.0" || fail "新机器余额异常: $NEW_BAL"
[ "$LIC_BAL" = "0.0" ] && pass "license 余额已清零" || fail "license 余额异常: $LIC_BAL"
[ "$LIC_MIG" = "1" ] && pass "migrated_to_machine 已置 1" || fail "migrated 标志异常: $LIC_MIG"

echo "--- 回归 V2: 调整积分只影响该机器 (MA 应不变) ---"
MA_BEFORE=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
curl -s -X POST "$BASE/admin/licenses/$LICENSE/adjust" -H "authorization: Bearer $ADMIN" -H "content-type: application/json" -d "{\"amount\":3.0,\"reason\":\"v2test\",\"machine_id\":\"$MB\"}" >/dev/null
MA_AFTER=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
MB_AFTER=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MB';")
echo "  调 MB+3 前后: MA=$MA_BEFORE → $MA_AFTER (应不变), MB → $MB_AFTER"
[ "$MA_BEFORE" = "$MA_AFTER" ] && pass "调 MB 不影响 MA" || fail "MA 被污染: $MA_BEFORE → $MA_AFTER"
# 还原 MB
curl -s -X POST "$BASE/admin/licenses/$LICENSE/adjust" -H "authorization: Bearer $ADMIN" -H "content-type: application/json" -d "{\"amount\":-3.0,\"reason\":\"v2test restore\",\"machine_id\":\"$MB\"}" >/dev/null

echo ""
echo "=== V4 [Bug#4]: ensure_columns 累加式迁移（重启触发）==="
echo "--- 当前 MA 余额 ---"
MA_BEFORE=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
echo "  MA=$MA_BEFORE"
echo "--- 给 license 设 3.0 待分配余额，migrated_to_machine=0 ---"
sqlite3 $DB "UPDATE licenses SET balance_credits=3.0, migrated_to_machine=0 WHERE license_key='$LICENSE';"
echo "--- 重启服务触发 ensure_columns ---"
systemctl restart social-ai-credit.service
sleep 2
systemctl is-active social-ai-credit.service
MA_AFTER=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM license_activations WHERE machine_id='$MA';")
LIC_BAL=$(sqlite3 $DB "SELECT round(balance_credits,4) FROM licenses WHERE license_key='$LICENSE';")
LIC_MIG=$(sqlite3 $DB "SELECT migrated_to_machine FROM licenses WHERE license_key='$LICENSE';")
echo "  重启后: MA=$MA_BEFORE → $MA_AFTER (期望累加 3.0 → $(echo "$MA_BEFORE + 3.0" | bc))"
echo "  license余额=$LIC_BAL (期望=0) migrated=$LIC_MIG (期望=1)"

EXPECT_MA=$(echo "$MA_BEFORE + 3.0" | bc)
[ "$MA_AFTER" = "$EXPECT_MA" ] && pass "ensure_columns 累加式迁移正确" || fail "MA 异常: $MA_BEFORE → $MA_AFTER (期望 $EXPECT_MA)"
[ "$LIC_BAL" = "0.0" ] && pass "license 余额已清零" || fail "license 余额异常: $LIC_BAL"

echo ""
echo "=== 清理测试数据 ==="
# 删除 V3 测试机器
sqlite3 $DB "DELETE FROM license_activations WHERE machine_id LIKE 'saam_bug3test_%';"
# 恢复 unknown 机器为 active
sqlite3 $DB "UPDATE license_activations SET status='active' WHERE machine_id='$UNK' AND license_key='$LICENSE';"
# 扣回 V4 测试加的 3.0
sqlite3 $DB "UPDATE license_activations SET balance_credits=balance_credits-3.0 WHERE machine_id='$MA';"
# 清零 license 余额（保险）
sqlite3 $DB "UPDATE licenses SET balance_credits=0, migrated_to_machine=1 WHERE license_key='$LICENSE';"

echo "--- 清理后最终状态 ---"
sqlite3 -header -column $DB "SELECT 'license' AS t, license_key AS id, round(balance_credits,4) AS bal, migrated_to_machine AS mig FROM licenses WHERE license_key='$LICENSE' UNION ALL SELECT 'MA', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$MA' UNION ALL SELECT 'MB', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$MB' UNION ALL SELECT 'UNK', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$UNK';"
echo "  active 机器数=$(sqlite3 $DB "SELECT count(*) FROM license_activations WHERE license_key='$LICENSE' AND status='active';")"

echo ""
echo "================== 结果汇总 =================="
echo "  PASS: $OK"
echo "  FAIL: $FAIL"
[ $FAIL -eq 0 ] && echo "  ✓ 全部通过" || echo "  ✗ 存在失败"
