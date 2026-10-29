# -*- coding: utf-8 -*-
"""
api_connector.py - 企业工商信息API连接器

支持多种API接入：
1. 国家企业信用信息公示系统 API
2. 天眼查 API
3. 企查查 API
4. 数脉 API
5. 本地数据优先策略

配置说明：
在项目根目录下创建 config.json：
{
  "api": {
    "tianyancha": {
      "api_key": "your_api_key",
      "enabled": true
    },
    "qcc": {
      "api_key": "your_api_key",
      "enabled": false
    },
    "shumai": {
      "app_id": "your_app_id",
      "app_secret": "your_app_secret",
      "enabled": false
    }
  }
}
"""

import sys
import json
import os
import requests
import hashlib
import time
from typing import Dict, List, Optional, Any
from datetime import datetime

if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


class CompanyInfoAPIConnector:
    """企业工商信息API连接器"""

    def __init__(self, config_path: str = None):
        """初始化连接器"""
        self.config = self._load_config(config_path)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def _load_config(self, config_path: str = None) -> Dict:
        """加载配置文件"""
        default_config = {
            'api': {
                'tianyancha': {'api_key': '', 'enabled': False},
                'qcc': {'api_key': '', 'enabled': False},
                'shumai': {'app_id': '', 'app_secret': '', 'enabled': False}
            },
            'priority': ['tianyancha', 'qcc', 'shumai']
        }

        if config_path and os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    user_config = json.load(f)
                default_config.update(user_config)
                print(f"✅ 配置加载成功: {config_path}")
            except Exception as e:
                print(f"⚠️ 配置加载失败: {e}")

        return default_config

    def get_company_info(self, company_name: str, use_local_first: bool = True,
                         data_dir: str = None) -> Dict:
        """获取企业信息（优先使用本地数据）

        Args:
            company_name: 企业名称
            use_local_first: 是否优先使用本地数据
            data_dir: 本地数据目录

        Returns:
            企业信息字典
        """
        result = {
            'company_name': company_name,
            'source': '',
            'success': False,
            'data': {},
            'error': None
        }

        # 1. 优先使用本地数据
        if use_local_first and data_dir:
            local_data = self._load_local_data(company_name, data_dir)
            if local_data:
                print(f"✅ 使用本地数据: {company_name}")
                result.update(local_data)
                return result

        # 2. 按优先级尝试API
        for api_name in self.config['priority']:
            api_config = self.config['api'].get(api_name, {})
            if not api_config.get('enabled', False):
                continue

            print(f"🔍 尝试API: {api_name}")
            try:
                if api_name == 'tianyancha':
                    api_result = self._query_tianyancha(company_name, api_config)
                elif api_name == 'qcc':
                    api_result = self._query_qcc(company_name, api_config)
                elif api_name == 'shumai':
                    api_result = self._query_shumai(company_name, api_config)
                else:
                    continue

                if api_result.get('success'):
                    result.update(api_result)

                    if data_dir:
                        self._save_to_cache(api_result, company_name, data_dir)

                    return result
            except Exception as e:
                print(f"⚠️ API {api_name} 失败: {e}")
                result['error'] = str(e)
                continue

        result['error'] = '所有API均无法获取数据'
        return result

    def _load_local_data(self, company_name: str, data_dir: str) -> Optional[Dict]:
        """从本地加载数据"""
        files_to_check = [
            os.path.join(data_dir, f"gsxt_{company_name}.json"),
            os.path.join(data_dir, "structure.json"),
        ]

        for filepath in files_to_check:
            if os.path.exists(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        data = json.load(f)

                    if 'structure.json' in filepath:
                        return self._extract_from_structure(data, company_name)
                    else:
                        return {
                            'source': 'local_cache',
                            'success': True,
                            'data': data.get('data', data)
                        }
                except Exception as e:
                    print(f"⚠️ 本地数据加载失败: {e}")

        return None

    def _extract_from_structure(self, data: Dict, company_name: str) -> Optional[Dict]:
        """从structure.json中提取数据"""
        result = {
            'source': 'structure.json',
            'success': False,
            'data': {}
        }

        # 提取股东信息
        shareholders = data.get('top_shareholders', [])
        if shareholders:
            result['data']['shareholders'] = shareholders
            result['success'] = True

        # 提取股权穿透
        equity_penetration = data.get('equity_penetration', [])
        if equity_penetration:
            result['data']['equity_penetration'] = equity_penetration

        # 提取实际控制人
        actual_controller = data.get('actual_controller', {})
        if actual_controller:
            result['data']['actual_controller'] = actual_controller

        return result if result['success'] else None

    def _save_to_cache(self, api_result: Dict, company_name: str, data_dir: str):
        """保存到本地缓存"""
        try:
            os.makedirs(data_dir, exist_ok=True)
            filepath = os.path.join(data_dir, f"api_{company_name}.json")
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(api_result, f, ensure_ascii=False, indent=2)
            print(f"✅ 缓存已保存: {filepath}")
        except Exception as e:
            print(f"⚠️ 缓存保存失败: {e}")

    def _query_tianyancha(self, company_name: str, config: Dict) -> Dict:
        """查询天眼查API"""
        result = {'source': 'tianyancha', 'success': False, 'data': {}, 'error': None}

        api_key = config.get('api_key', '')
        if not api_key:
            result['error'] = '未配置天眼查API Key'
            return result

        url = "https://open.tianyancha.com/services/v3/search/company"
        params = {
            'word': company_name,
            'pageSize': 10
        }
        headers = {
            'Authorization': f'Bearer {api_key}'
        }

        try:
            response = self.session.get(url, params=params, headers=headers, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('data') and data['data'].get('list'):
                result['data'] = data['data']['list'][0]
                result['success'] = True
            else:
                result['error'] = '未找到企业信息'

        except Exception as e:
            result['error'] = str(e)

        return result

    def _query_qcc(self, company_name: str, config: Dict) -> Dict:
        """查询企查查API"""
        result = {'source': 'qcc', 'success': False, 'data': {}, 'error': None}

        api_key = config.get('api_key', '')
        if not api_key:
            result['error'] = '未配置企查查API Key'
            return result

        url = "https://api.qcc.com/ECIFuzzySearch"
        params = {
            'key': api_key,
            'searchKey': company_name
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('Status') == 200 and data.get('Result'):
                result['data'] = data['Result'].get('Items', [])[0]
                result['success'] = True
            else:
                result['error'] = data.get('Message', '查询失败')

        except Exception as e:
            result['error'] = str(e)

        return result

    def _query_shumai(self, company_name: str, config: Dict) -> Dict:
        """查询数脉API"""
        result = {'source': 'shumai', 'success': False, 'data': {}, 'error': None}

        app_id = config.get('app_id', '')
        app_secret = config.get('app_secret', '')

        if not app_id or not app_secret:
            result['error'] = '未配置数脉API凭证'
            return result

        timestamp = str(int(time.time() * 1000))
        sign_str = f"{app_id}&{timestamp}&{app_secret}"
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

        url = "https://api.shumaidata.com/v4/special-business/query"
        params = {
            'appid': app_id,
            'timestamp': timestamp,
            'sign': sign,
            'companyName': company_name
        }

        try:
            response = self.session.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            if data.get('code') == 200 or data.get('success'):
                result['data'] = data.get('data', {})
                result['success'] = True
            else:
                result['error'] = data.get('message', '查询失败')

        except Exception as e:
            result['error'] = str(e)

        return result


def create_config_template(output_path: str = "config.json"):
    """创建配置文件模板"""
    template = {
        "api": {
            "tianyancha": {
                "api_key": "your_tianyancha_api_key_here",
                "enabled": false
            },
            "qcc": {
                "api_key": "your_qcc_api_key_here",
                "enabled": false
            },
            "shumai": {
                "app_id": "your_shumai_app_id_here",
                "app_secret": "your_shumai_app_secret_here",
                "enabled": false
            }
        },
        "priority": ["tianyancha", "qcc", "shumai"]
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(template, f, ensure_ascii=False, indent=2)

    print(f"✅ 配置模板已创建: {output_path}")


if __name__ == '__main__':
    import sys

    if len(sys.argv) >= 2 and sys.argv[1] == 'init':
        create_config_template()
        print("\n配置说明:")
        print("1. 编辑 config.json，填入你的API密钥")
        print("2. 将 enabled 设置为 true 启用对应API")
        print("3. 运行测试: python api_connector.py test 纳思达股份有限公司")
    elif len(sys.argv) >= 3 and sys.argv[1] == 'test':
        company_name = sys.argv[2]
        data_dir = sys.argv[3] if len(sys.argv) > 3 else None

        print(f"\n{'='*60}")
        print(f"API测试: {company_name}")
        print(f"{'='*60}")

        connector = CompanyInfoAPIConnector()
        result = connector.get_company_info(company_name, data_dir=data_dir)

        print(f"\n结果:")
        print(f"  状态: {'✅ 成功' if result['success'] else '❌ 失败'}")
        print(f"  来源: {result['source']}")
        if result.get('error'):
            print(f"  错误: {result['error']}")
        if result.get('data'):
            print(f"  数据: {json.dumps(result['data'], ensure_ascii=False, indent=2)[:500]}...")
    else:
        print("用法:")
        print("  python api_connector.py init          - 创建配置文件模板")
        print("  python api_connector.py test <企业名> [数据目录] - 测试API连接")
