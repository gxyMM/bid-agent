import json
import subprocess
import fitz # PyMuPDF
import os
import re
import sys

# ================= 5万级系统配置 =================
BASE_TOKEN = os.getenv("FEISHU_BASE_TOKEN", "YOUR_BASE_TOKEN")
TABLE_ID = os.getenv("FEISHU_TABLE_ID", "YOUR_TABLE_ID")

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
        current_logic_page = 0  # 【修复 1】引入游标，解决自增算法失效导致页码卡死的问题
        
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

    def _get_context_window(self, text, keywords, window_size=150):
        """【修复 5】以关键字为中心提取滑动窗口上下文，避免暴力切片导致证据断裂"""
        text = text.replace('\n', ' ')
        first_kw = keywords[0]
        idx = text.find(first_kw)
        if idx == -1:
            return text[:window_size * 2]
        
        start = max(0, idx - window_size)
        end = min(len(text), idx + len(first_kw) + window_size)
        return "..." + text[start:end] + "..."

    def run_audit(self):
        print("🔍 正在根据映射表进行精准审计...")
        
        # 预设的专业审计建议库 (生产环境由 LLM 生成)
        ADVICE_LIB = {
            "投标有效期天数": "【风控建议】已识别甲方要求为 120 天。请投标专员务必核对投标文件中的有效期声明，确保不低于 120 天，否则将被视为实质性不响应而导致废标。",
            "法人电子签章要求": "【风控建议】本项为形式审查的致命红线。请检查电子投标系统中是否已正确关联法人私章，确保《投标函》等关键页面具备双重签章。",
            "三大件品牌一致性": "【风控建议】★号强制性参数。请核实球管、探测器、高压发生器是否为同一品牌。若存在品牌拼凑，请立刻更换方案，否则技术标将直接不合格。"
        }

        for name, cfg in AUDIT_CONFIG.items():
            found = False
            for i in range(len(self.doc)):
                page = self.doc[i]
                text = page.get_text()
                
                # 【修复 2】引入 TOC 拦截机制，防止在目录页直接触发误判
                toc_kw = cfg.get("toc_keyword")
                if toc_kw and toc_kw in text[:300]: 
                    continue
                
                if all(kw in text for kw in cfg["keywords"]):
                    logic_p = self.phys_to_logic.get(i + 1, i + 1)
                    
                    # 【修复 6】移除了此处原先冗余的针对“投标有效期”的 blocks 正则反向查找逻辑
                    
                    print(f"🎯 [命中] {name} | 物理位置: P{i+1} | 逻辑页码: {logic_p}")
                    
                    # 提取中心上下文证据
                    context_evidence = self._get_context_window(text, cfg["keywords"])
                    
                    # 获取业务建议
                    business_advice = ADVICE_LIB.get(name, "已完成定位，请根据标书要求进行核对。")
                    
                    self.sync_to_feishu(name, context_evidence, logic_p, business_advice)
                    found = True
                    break
            
            if not found:
                print(f"❌ 未命中: {name}")

    def sync_to_feishu(self, point, text, page, advice):
        fields = {
            "审计考点": point,
            "风险条款原文": text.strip(),
            "证据页码": page,
            "风险等级": "🟢 完全匹配", # 演示版暂定，生产环境由 LLM 判定
            "AI诊断指令": advice,
            "项目名称": os.path.basename(self.pdf_path)
        }
        json_payload = json.dumps(fields, ensure_ascii=False)
        
        # 【修复 3】补充 --as bot 参数，并增加飞书接口返回值的校验逻辑
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
            print(f"✅ 成功同步证据链至飞书多维表: {point}")

if __name__ == "__main__":
    engine = ZeroHallucinationEngine(RFP_PATH)
    engine.run_audit()
