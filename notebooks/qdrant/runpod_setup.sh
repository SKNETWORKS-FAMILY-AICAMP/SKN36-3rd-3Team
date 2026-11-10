#!/usr/bin/env bash
# Runpod(PyTorch CUDA 템플릿) Pod에서 임베딩 A/B 테스트 준비 스크립트
# 사용: Jupyter Lab 터미널에서  bash runpod_setup.sh
# 하는 일: Ollama 설치·모델 pull·GPU 사용 확인, 파이썬 패키지 설치, KURE-v1 사전 다운로드(revision 고정), 환경 요약 출력
set -euo pipefail

QWEN_MODEL="qwen3-embedding:0.6b"
EXPECTED_DIGEST_PREFIX="ac6da0dfba84"          # 로컬 PC에서 확인한 digest 앞부분 (같은 모델인지 확인)
KURE_REV="8b418a58414668e75532ed045c22d9ca018ae2b2"
QWEN_TOK_REV="97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"

echo "== [1/5] GPU 확인"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv || { echo "GPU가 보이지 않습니다. Pod 템플릿을 확인하세요."; exit 1; }

echo "== [2/5] Ollama 설치 및 서버 시작"
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi
if ! curl -s http://localhost:11434/api/version >/dev/null 2>&1; then
  nohup ollama serve > /workspace/ollama_server.log 2>&1 &
  for i in $(seq 1 30); do curl -s http://localhost:11434/api/version >/dev/null 2>&1 && break; sleep 1; done
fi
curl -s http://localhost:11434/api/version; echo
ollama pull "$QWEN_MODEL"
DIGEST=$(curl -s http://localhost:11434/api/tags | python3 -c "import json,sys; d=json.load(sys.stdin); print(next(m['digest'] for m in d['models'] if m['name']=='$QWEN_MODEL'))")
echo "digest: $DIGEST"
case "$DIGEST" in
  ${EXPECTED_DIGEST_PREFIX}*) echo "digest 일치 (로컬과 같은 모델)";;
  *) echo "경고: digest가 로컬(${EXPECTED_DIGEST_PREFIX}…)과 다릅니다. run_meta에 그대로 기록되니 보고서에 명시하세요.";;
esac

echo "== [3/5] Ollama GPU 사용 확인 (size_vram > 0 이어야 함)"
curl -s http://localhost:11434/api/embed -d "{\"model\":\"$QWEN_MODEL\",\"input\":\"준비\"}" >/dev/null
curl -s http://localhost:11434/api/ps | python3 -c "
import json,sys; d=json.load(sys.stdin)
for m in d.get('models',[]):
    print(m['name'], 'size_vram =', m.get('size_vram'))
    if not m.get('size_vram'): print('경고: Ollama가 GPU를 쓰지 않고 있습니다(CPU 폴백). 드라이버/CUDA 확인 필요'); sys.exit(1)
"

echo "== [4/5] 파이썬 패키지 설치"
pip install -q --upgrade pip
pip install -q "sentence-transformers" "transformers" "langchain-core" "langchain-community" "langchain-ollama" \
  "langchain-huggingface" "langchain-qdrant" "qdrant-client" "ollama" "jq" "pandas" "numpy" "ipykernel"
python3 - <<'EOF'
import torch, importlib.metadata as im
print("torch", torch.__version__, "| cuda build", torch.version.cuda, "| cuda available", torch.cuda.is_available(),
      "|", torch.cuda.get_device_name(0) if torch.cuda.is_available() else "GPU 없음")
for p in ["sentence-transformers","transformers","langchain-ollama","langchain-huggingface","langchain-qdrant","qdrant-client","ollama","langchain-community","jq"]:
    print(f"{p:24s} {im.version(p)}")
EOF

echo "== [5/5] KURE-v1 / Qwen 토크나이저 사전 다운로드 (revision 고정)"
python3 - <<EOF
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer
m = SentenceTransformer("nlpai-lab/KURE-v1", device="cuda", revision="$KURE_REV")
print("KURE-v1 로드 OK | max_seq_length", m.max_seq_length, "| device", m.device, "| dtype", next(m.parameters()).dtype)
AutoTokenizer.from_pretrained("Qwen/Qwen3-Embedding-0.6B", revision="$QWEN_TOK_REV"); print("Qwen 토크나이저 OK")
EOF

echo
echo "준비 완료. 다음: Jupyter에서 03_embedding_ab_test.ipynb 열기 → 설정 셀의 DATA_ROOT를 업로드한 청크 폴더로 수정 → 1번 셀부터 순서대로 실행"
echo "작업이 끝나면 results/<run_id>/ 를 내려받고 Pod를 Terminate 하세요."
