import json
import subprocess
import fitz # PyMuPDF
import os
import re
import sys
import requests

# ================= 5万级系统配置 =================
BASE_TOKEN = os.getenv("FEISHU_BASE_TOKEN", "YOUR_BASE_TOKEN")
TABLE_ID = os.getenv("FEISHU_TABLE_ID", "YOUR_TABLE_ID")

# ================= LLM API 配置 =================
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4-turbo")

# 【修复 4】移除硬编码绝对路径，支持命令行传参或回退到默认测试文件
RFP_PATH = sys.argv[1] if len(sys.argv) > 1 else os.getenv("RFP_PATH", "./sample_rfp.pdf")

# 审计点配置
AUDIT_CONFIG = {
    "投标有效期天数": {"keywords": ["投标有效期", "120"], "toc_keyword": "目录"},
    "法人电子签章要求": {"keywords": ["法定代表人", "电子签章"], "toc_keyword": "目录"},
    "三大件品牌一致性": {"keywords": ["球管", "同一品牌"], "toc_keyword": "目录"}
}
# ===============================================

class ZeroHallucinationEngine:
    def __init__(self, pdf_path):
        if not os.path.exists(pdf_path):
            print(f"❌ 找不到文件: {pdf_path}。请通过命令行参数传入正确的 PDF 路径，例如: python main_audit_engine.py /path/to/rfp.pdf")
            sys.exit(1)
            
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)
        self.phys_to_logic = {} # 物理页码 -> 逻辑页码 (1-based)
        print(f"🚀 启动零幻觉审计引擎：{os.path.basename(pdf_path)}")
        self._build_visual_index()

    def _build_visual_index(self):
        """第一阶段：视觉感知。扫描全书脚部，建立真实的页码映射表"""
        print("📸 正在进行视觉扫描，构建页码映射表...")
        current_logic_page = 0  # 引入游标，解决自增算法失效导致页码卡死的问题
        
        for i in range(len(self.doc)):
            page = self.doc[i]
            rect = page.rect
            # 锁定底部 80 像素的黄金区域 (页码最常出现的位置)
            footer_rect = fitz.Rect(0, max(0, rect.height - 80), rect.width, rect.height)
            footer_text = page.get_textbox(footer_rect).replace(" ", "") # 去掉所有空格
            
            # 匹配逻辑：找“第x页”、“x/81”或者孤立的数字
            match = re.search(r"第(\d+)页", footer_text)
            if match:
                current_logic_page = int(match.group(1))
            else:
                # 如果这页没印页码，根据前一页自动递增
                current_logic_page += 1
                
            self.phys_to_logic[i + 1] = current_logic_page

    def _get_context_window(self, text, keywords, window_size=300):
        """以关键字为中心提取滑动窗口上下文，传给大模型做 RAG 推理"""
        text = text.replace('\n', ' ')
        first_kw = keywords[0]
        idx = text.find(first_kw)
        if idx == -1:
            return text[:window_size * 2]
        
        start = max(0, idx - window_size)
        end = min(len(text), idx + len(first_kw) + window_size)
        return "..." + text[start:end] + "..."

    def _call_llm_auditor(self, rule_name, context):
        """核心大脑：调用大模型执行专家审计"""
        print(f"🧠 正在请求大模型 ({LLM_MODEL}) 进行风控判决：{rule_name}...")
        
        prompt_path = os.path.join(os.path.dirname(__file__), "prompts", "stage2_rule_scanner.md")
        system_prompt = "你是一个严厉的废标审查专家。"
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                system_prompt = f.read()

        user_prompt = f"当前审查规则：{rule_name}\n标书上下文原文片段：\n{context}\n\n请根据 System Prompt 里的要求，判断这段内容是否存在废标风险。请直接输出合规的 JSON 对象，包含字段：rule_name, violation_type, severity, advice(专家指令，给出具体的【甲方的刀】、【乙方的盾】结构)。"

        if not LLM_API_KEY:
            return {"advice": "⚠️ 未配置大模型 API Key。目前为 MVP 兜底响应：已命中关键字位置，请人工核对！(若要激活AI智能审查，请配置 LLM_API_KEY 环境变量)"}

        try:
            headers = {
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": LLM_MODEL,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "response_format": {"type": "json_object"}
            }
            res = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=45)
            res.raise_for_status()
            data = res.json()
            content = data['choices'][0]['message']['content']
            # 清理可能的 markdown 代码块标记
            content = content.replace("```json", "").replace("```", "").strip()
            return json.loads(content)
        except Exception as e:
            return {"advice": f"❌ 大模型调用出错: {str(e)}"}

    def run_audit(self):
        print("🔍 正在根据映射表与大模型进行精准审计...")
        
        for name, cfg in AUDIT_CONFIG.items():
            found = False
            for i in range(len(self.doc)):
                page = self.doc[i]
                text = page.get_text()
                
                # 引入 TOC 拦截机制，防止在目录页直接触发误判
                toc_kw = cfg.get("toc_keyword")
                if toc_kw and toc_kw in text[:300]: 
                    continue
                
                if all(kw in text for kw in cfg["keywords"]):
                    logic_p = self.phys_to_logic.get(i + 1, i + 1)
                    print(f"🎯 [视觉锚点命中] {name} | 物理位置: P{i+1} | 逻辑页码: {logic_p}")
                    
                    # 1. 提取中心上下文证据
                    context_evidence = self._get_context_window(text, cfg["keywords"])
                    
                    # 2. 交给大模型判断
                    llm_result = self._call_llm_auditor(name, context_evidence)
                    business_advice = llm_result.get("advice", str(llm_result))
                    
                    # 3. 将大模型的判决结果同步给业务层 (飞书多维表)
                    self.sync_to_feishu(name, context_evidence, logic_p, business_advice)
                    found = True
                    break
            
            if not found:
                print(f"❌ 全文未命中: {name}")

    def sync_to_feishu(self, point, text, page, advice):
        fields = {
            "审计考点": point,
            "风险条款原文": text.strip(),
            "证据页码": page,
            "风险等级": "🔴 大模型研判完成", 
            "AI诊断指令": advice,
            "项目名称": os.path.basename(self.pdf_path)
        }
        json_payload = json.dumps(fields, ensure_ascii=False)
        
        cmd = [
            "lark-cli", "base", "+record-upsert", 
            "--base-token", BASE_TOKEN, 
            "--table-id", TABLE_ID, 
            "--json", json_payload,
            "--as", "bot"
        ]
        
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"❌ 飞书写入失败: {res.stderr.strip()}")
        else:
            print(f"✅ 成功同步包含 AI 诊断的证据链至飞书多维表: {point}")

if __name__ == "__main__":
    engine = ZeroHallucinationEngine(RFP_PATH)
    engine.run_audit()
