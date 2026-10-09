# Intent Recognition Training Resources for DocIntake Chatbot

## Purpose
Train the model to better understand human intent in chat conversations — particularly for service onboarding applications.

## Top Datasets (Free/Open)

### 1. WildChat (650K+ conversations)
- **URL**: https://huggingface.co/datasets/shreysachdeva/WildChat
- **What**: Real human↔ChatGPT conversations covering ambiguous requests, code-switching, topic-switching
- **Use**: Instruction fine-tuning, studying real user behavior patterns

### 2. LMSYS-Chat-1M (1M+ conversations)
- **URL**: https://huggingface.co/datasets/lmsys/lmsys-chat-1m
- **What**: Real-world conversations with 25 LLMs from Chatbot Arena
- **Use**: Instruction fine-tuning, benchmarking, content moderation

### 3. ShareChat (142K conversations, 660K+ turns)
- **URL**: https://huggingface.co/datasets/tucnguyen/ShareChat
- **What**: Conversations from ChatGPT, Perplexity, Grok, Gemini, Claude — 95 languages
- **Use**: Multi-platform interaction patterns, long conversations (avg 4.6 turns)

### 4. REALTALK (Real-world long-term dialogues)
- **URL**: https://arxiv.org/pdf/2502.13270v1.pdf
- **What**: 21-day authentic messaging app dialogues — emotional intelligence, persona consistency
- **Use**: Studying how real conversations build over time (not LLM-simulated)

### 5. Bench-Labs Conversations-Human-AI-100k
- **URL**: https://huggingface.co/datasets/bench-labs/Conversations-Human-AI-100k
- **What**: Multi-turn conversations where user pushed back, followed up, or probed
- **Use**: Training for genuine reasoning and intent clarification

### 6. UltraChat (1.5M dialogues)
- **URL**: https://github.com/thunlp/UltraChat
- **What**: Multi-turn instructional conversations (Questions, Creation, Assistance)
- **Use**: Instruction-following fine-tuning

### 7. Ecom-Chatbot-Finetuning-Dataset (40K records)
- **URL**: https://huggingface.co/datasets/rescommons/Ecom-Chatbot-Finetuning-Dataset
- **What**: E-commerce customer service — product queries, order management, returns, complaints
- **Use**: Intent hierarchy training (category→intent→sub_intent), multi-turn task handling

### 8. IntentGrasp (262K instances)
- **URL**: https://huggingface.co/datasets/yuweiyin/IntentGrasp
- **What**: 12 domains: daily life, smart assistant, customer support, empathetic response, etc.
- **Use**: Intent understanding evaluation and fine-tuning

### 9. Chain-of-Intent / MINT-E
- **URL**: https://arxiv.org/html/2411.14252v3
- **What**: Multilingual e-commerce multi-turn dialogues generated from real chat logs
- **Use**: Intent transition patterns, multi-turn classification training

## Key Research Papers

### 1. REIC: RAG-Enhanced Intent Classification at Scale (ACL 2025)
- **URL**: https://arxiv.org/html/2506.00210
- **Key Insight**: RAG + fine-tuned LLM outperforms traditional fine-tuning for intent classification at scale
- **For your project**: Use retrieval-augmented intent detection instead of retraining

### 2. LARA: Linguistic-Adaptive Retrieval-Augmentation (ACL 2025)
- **URL**: https://arxiv.org/html/2403.16504v3
- **Key Insight**: Combines fine-tuned small model + retrieval for multi-turn intent classification
- **For your project**: Great for your chatbot's multi-turn context handling

### 3. Dial-In LLM: Human-Aligned Intent Clustering (ACL 2025)
- **URL**: https://aclanthology.org/2025.acl-long.464.pdf
- **Key Insight**: LLM-in-the-loop intent clustering achieves 95%+ human alignment
- **For your project**: Use LLM to discover and name intent clusters from your chat logs

### 4. BlendX: Complex Multi-Intent Detection (Arxiv 2024)
- **URL**: https://arxiv.deeppaper.ai/papers/2403.18277v1
- **Key Insight**: Users express multiple intents in a single utterance
- **For your project**: Handle compound intents like "I want to apply for basic registration AND upload my ID"

### 5. RAG System Model Evolution Guide
- **URL**: https://alexandernarbaev.github.io/rag-system/guides/model-evolution/
- **Key Insight**: Three-model fine-tuning pipeline — SLM (intent classifier), LLM (generator), Reranker
- **For your project**: Train a small intent classifier on your actual query distribution

## Quick Start Recommendation

For your project (local model + FastAPI chatbot + onboarding wizard):

1. **Immediate** — Use the dataset already in your project's `faq_catalog.json` and `ROUTING_POLICIES.md`
2. **Short-term** — Collect real chat logs from your current bot and fine-tune intent classification on them
3. **Medium-term** — Use WildChat + ShareChat for instruction fine-tuning (if you have GPU)
4. **Long-term** — Implement the REIC approach: build a vector index of (query, intent) pairs and use RAG at inference time

## Fine-Tuning Pipeline (from RAG System Guide)

```
1. Collect HITL feedback → logs/hitl.jsonl
2. Process into 3 datasets:
   - slm_intent.jsonl      → Intent classifier (SLM fine-tuning)
   - llm_instruction.jsonl → Answer generation (LLM fine-tuning)
   - reranker_pairs.jsonl  → Relevance scoring (Reranker fine-tuning)
3. Train with LoRA (QLoRA for LLM, ~5-50MB adapter)
4. Deploy to SageMaker/local endpoint
```

For your RTX 4060 Laptop (8GB VRAM):
- QLoRA fine-tuning with 4-bit NF4 quantization
- Base model: Qwen2.5 3B or Llama-3.2 3B (fits in 8GB)
- LoRA rank=8, alpha=16, dropout=0.1
- Batch size=4, gradient accumulation=4
