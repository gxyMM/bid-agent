import os
import requests
import json
import time
from requests_toolbelt import MultipartEncoder

# --- 飞书凭证配置 ---
# 请确保这些环境变量或配置已就绪
APP_ID = os.getenv("FEISHU_APP_ID", "YOUR_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET", "") # 建议通过环境变量读取
APP_TOKEN = "YOUR_BASE_TOKEN" # 多维表格Token
TABLE_ID = "YOUR_TABLE_ID" # 任务表ID

class FeishuBatchUploader:
    def __init__(self, app_id, app_secret):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = self._get_token()

    def _get_token(self):
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        res = requests.post(url, json={"app_id": self.app_id, "app_secret": self.app_secret})
        return res.json().get("tenant_access_token")

    def upload_file(self, file_path):
        """上传单个文件并获取 file_token"""
        print(f"☁️ 正在上传文件: {os.path.basename(file_path)}")
        url = "https://open.feishu.cn/open-apis/drive/v1/medias/upload_all"
        file_name = os.path.basename(file_path)
        
        with open(file_path, 'rb') as f:
            form = {
                'file_name': file_name,
                'parent_type': 'bitable',
                'parent_node': APP_TOKEN,
                'size': str(os.path.getsize(file_path)),
                'file': (file_name, f, 'application/octet-stream')
            }
            m = MultipartEncoder(form)
            headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': m.content_type}
            res = requests.post(url, headers=headers, data=m)
            return res.json().get("data", {}).get("file_token")

    def create_record(self, project_name, rfp_token, draft_token):
        """在多维表中创建一条包含两个附件的记录"""
        url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{APP_TOKEN}/tables/{TABLE_ID}/records"
        headers = {'Authorization': f'Bearer {self.token}', 'Content-Type': 'application/json'}
        
        fields = {
            "项目名称": project_name,
            "招标文件": [{"file_token": rfp_token}] if rfp_token else [],
            "投标文件": [{"file_token": draft_token}] if draft_token else []
        }
        
        res = requests.post(url, headers=headers, json={"fields": fields})
        if res.json().get("code") == 0:
            print(f"✅ 项目 [{project_name}] 导入成功！")
        else:
            print(f"❌ 导入失败: {res.json().get('msg')}")

def run_batch_import(folder_path):
    uploader = FeishuBatchUploader(APP_ID, APP_SECRET)
    files = os.listdir(folder_path)
    
    # 简单的项目配对逻辑：基于文件名前缀
    projects = {}
    for f in files:
        if not f.endswith(".pdf"): continue
        # 假设文件名格式为：项目名_类型.pdf
        name_parts = f.split("_")
        project_name = name_parts[0]
        file_type = "RFP" if "招标" in f else "DRAFT"
        
        if project_name not in projects:
            projects[project_name] = {"RFP": None, "DRAFT": None}
        
        full_path = os.path.join(folder_path, f)
        token = uploader.upload_file(full_path)
        projects[project_name][file_type] = token
        
    for p_name, tokens in projects.items():
        uploader.create_record(p_name, tokens["RFP"], tokens["DRAFT"])

if __name__ == "__main__":
    # 示例用法：python3 batch_uploader.py /path/to/your/bids
    import sys
    if len(sys.argv) > 1:
        run_batch_import(sys.argv[1])
    else:
        print("💡 请提供包含标书文件的文件夹路径。")
