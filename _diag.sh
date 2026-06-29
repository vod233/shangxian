#!/bin/bash
DB="/www/wwwroot/CloudSever.lcjx.yun/app/data/credit_server.db"
SRV="/www/wwwroot/CloudSever.lcjx.yun/app/credit_server/server.py"
LICENSE="saa_DTFje43GdrtsYwWtax3xi5xQ79HOhT5o"

echo "=== A. 服务状态 ==="
systemctl is-active social-ai-credit.service
echo ""

echo "=== B. license 表当前状态 ==="
sqlite3 -header -column $DB "SELECT license_key, balance_credits, migrated_to_machine, status FROM licenses WHERE license_key='$LICENSE';"
echo ""

echo "=== C. 该 license 下所有激活的机器 ==="
sqlite3 -header -column $DB "SELECT machine_id, status, disabled, round(balance_credits,4) AS bal, round(spent_credits,4) AS spent, verify_count, round(rate_multiplier,3) AS mult FROM license_activations WHERE license_key='$LICENSE' ORDER BY verify_count DESC;"
echo ""
echo "机器总数:"
sqlite3 $DB "SELECT count(*) FROM license_activations WHERE license_key='$LICENSE' AND status='active';"
echo ""

echo "=== D. 服务器上实际部署的 register_activation 关键片段(行302-318) ==="
sed -n '302,318p' $SRV
echo ""

echo "=== E. 是否有遗留的 revtest 测试机器 ==="
sqlite3 -header -column $DB "SELECT machine_id, balance_credits, first_seen FROM license_activations WHERE machine_id LIKE 'saam_revtest%';"
echo ""

echo "=== F. 最近 admin_audit_logs (5条) ==="
sqlite3 -header -column $DB "SELECT id, action, target_id, created_at FROM admin_audit_logs ORDER BY id DESC LIMIT 5;" 2>/dev/null || echo "  (表不存在或为空)"
echo ""

echo "=== G. 最近 credit_adjustments (5条) ==="
sqlite3 -header -column $DB "SELECT id, license_key, machine_id, amount, round(balance_before,4) AS before_b, round(balance_after,4) AS after_b, reason, created_at FROM credit_adjustments ORDER BY id DESC LIMIT 5;" 2>/dev/null || echo "  (表不存在或为空)"
echo ""

echo "=== H. 服务最近10行日志 ==="
journalctl -u social-ai-credit.service -n 20 --no-pager 2>&1 | tail -20
