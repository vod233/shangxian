#!/bin/bash
SRV="/www/wwwroot/CloudSever.lcjx.yun/app/credit_server/server.py"

echo "=== 1. verify 端点定义 (搜索 @app.post auth/verify) ==="
grep -n "auth/verify\|def verify\|register_activation" $SRV | head -20

echo ""
echo "=== 2. verify_license 函数 ==="
grep -n "def verify_license\|def verify\b" $SRV

echo ""
echo "=== 3. 完整 verify 端点代码（找到行号后打印）==="
START=$(grep -n "@app.post.*auth/verify\|@app.post.*verify" $SRV | head -1 | cut -d: -f1)
if [ -n "$START" ]; then
  echo "从第 $START 行开始打印 60 行"
  sed -n "${START},$((START+60))p" $SRV
fi

echo ""
echo "=== 4. verify_license 函数实现 ==="
START2=$(grep -n "def verify_license" $SRV | head -1 | cut -d: -f1)
if [ -n "$START2" ]; then
  echo "从第 $START2 行开始打印 40 行"
  sed -n "${START2},$((START2+40))p" $SRV
fi
