#!/bin/bash
# 回滚 V3 测试污染的生产数据
DB="/www/wwwroot/CloudSever.lcjx.yun/app/data/credit_server.db"
LICENSE="saa_DTFje43GdrtsYwWtax3xi5xQ79HOhT5o"
MA="saam_066a2714863342ad8d3e80cd1f5ac702"

echo "=== 回滚前状态 ==="
sqlite3 -header -column $DB "SELECT 'license' AS t, license_key, balance_credits AS bal, migrated_to_machine AS mig FROM licenses WHERE license_key='$LICENSE' UNION ALL SELECT 'MA', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$MA';"

# 1. 恢复 MA 余额：补偿 984.878（从 8.0 恢复到 992.878，audit log id=11 的 after_b）
sqlite3 $DB "UPDATE license_activations SET balance_credits=balance_credits+984.878 WHERE machine_id='$MA';"

# 2. 清零 license 残留的 8.0 暂存余额
sqlite3 $DB "UPDATE licenses SET balance_credits=0 WHERE license_key='$LICENSE';"

# 3. 插入审计记录，便于追溯
NOW=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
sqlite3 $DB "INSERT INTO credit_adjustments(license_key, machine_id, amount, balance_before, balance_after, reason, operator, created_at) VALUES('$LICENSE','$MA',984.878,8.0,992.878,'V3测试污染回滚: ensure_columns覆盖式迁移bug导致MA余额被覆盖',$NOW);"

echo ""
echo "=== 回滚后状态 ==="
sqlite3 -header -column $DB "SELECT 'license' AS t, license_key, balance_credits AS bal, migrated_to_machine AS mig FROM licenses WHERE license_key='$LICENSE' UNION ALL SELECT 'MA', machine_id, round(balance_credits,4), 0 FROM license_activations WHERE machine_id='$MA';"
echo ""
echo "=== 最近审计记录 ==="
sqlite3 -header -column $DB "SELECT id, machine_id, amount, round(balance_before,4) AS before_b, round(balance_after,4) AS after_b, reason FROM credit_adjustments ORDER BY id DESC LIMIT 3;"
