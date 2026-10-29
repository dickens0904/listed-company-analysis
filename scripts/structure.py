# -*- coding: utf-8 -*-
"""
模块8：股权结构分析（AKShare增强版）
构建上市公司→子公司→关联方完整结构图
数据源: AKShare + 公告解析
"""
import sys, json, re
try:    # 2026-10-19 审计：静默降级登记
    from scripts.silenced_errors import record, record_result
except ImportError:
    from silenced_errors import record, record_result
sys.stdout.reconfigure(encoding='utf-8')

def _import_akshare():
    """延迟导入akshare"""
    try:
        import akshare as ak
        return ak
    except ImportError:
        print("  ⚠️ akshare未安装，股权结构分析功能受限")
        return None

ak = _import_akshare()

# 超时包装器
def _run_with_timeout(func, *args, timeout=30, **kwargs):
    """在线程中运行函数，超时后返回None"""
    import threading
    result = [None]
    exception = [None]
    
    def target():
        try:
            result[0] = func(*args, **kwargs)
        except Exception as e:
            exception[0] = e
    
    thread = threading.Thread(target=target)
    thread.daemon = True
    thread.start()
    thread.join(timeout=timeout)
    
    if thread.is_alive():
        print(f"  ⚠️ {func.__name__} 超时({timeout}秒)")
        return None
    
    if exception[0]:
        raise exception[0]
    
    return result[0]

# 延迟导入iwencai_provider
_iwencai = None
def _import_iwencai():
    global _iwencai
    if _iwencai is None:
        try:
            from iwencai_provider import query_iwencai
            _iwencai = query_iwencai
        except ImportError:
            print("  ⚠️ iwencai_provider未安装，跳过i问财数据源")
    return _iwencai


def _fetch_actual_controller_iwencai(stock_code):
    """i问财: 获取实际控制人
    
    查询词: "{股票代码} 实控人"
    返回字段: 实际控制人、股东名称、持股数量、持股比例、持股市值等
    """
    query_fn = _import_iwencai()
    if query_fn is None:
        return None
    code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    try:
        result = query_fn(
            skill_id='hithink-basicinfo-query',
            query=f"{code} 实控人 前十大股东",
            page=1,
            limit=5
        )
        if not result.get('success') or not result.get('datas'):
            return None
        first = result['datas'][0]
        controller = str(first.get('实际控制人', '')).strip()
        if not controller or controller == 'None' or controller == '无':
            return None
        return {
            "name": controller,
            "source": "i问财",
            "ratio_pct": _safe_float(first.get('持股比例')),
            "control_type": str(first.get('持股变动类型', '')),
        }
    except Exception as e:
        return None


def _fetch_shareholder_changes_iwencai(stock_code):
    """i问财: 获取股东持股变动记录
    
    两套查询互补:
    - 查询1 "前十大股东 增持 减持" → 覆盖完整(含 不变/新进/新出)，但部分股票无股东名称
    - 查询2 "增持 减持" → 有股东名称，但只有增减持记录
    
    合并策略: 先用查询1全部记录，再用查询2补充缺失的股东名称
    """
    query_fn = _import_iwencai()
    if query_fn is None:
        return []
    code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    try:
        # 查询1: 完整记录（含不变）
        result1 = query_fn(
            skill_id='hithink-basicinfo-query',
            query=f"{code} 前十大股东 增持 减持",
            page=1, limit=10
        )
        # 查询2: 有股东名称的记录（仅增减持，用于补充查询1缺失的股东名称）
        result2 = query_fn(
            skill_id='hithink-basicinfo-query',
            query=f"{code} 增持 减持",
            page=1, limit=10
        )
        if not (result1.get('success') and result1.get('datas')):
            return []
        changes = []
        # 收集查询2有股东名称的记录（用于与查询1合并去重）
        # key = (holder_name, ann_date) ，但holder_name可能为空
        # 改用 ann_date 作为去重key
        seen_dates_q2 = set()  # 查询2覆盖的日期（跳过查询1对应日期的"不变/新进/新出"）
        changes_q2 = []
        if result2.get('success') and result2.get('datas'):
            for row in result2['datas']:
                ann_date = str(row.get('公告日期', ''))
                change_type = str(row.get('持股变动类型', '') or row.get('变动方向', '')).strip()
                # query2的基本股票信息记录无change_type，过滤掉
                if not change_type or change_type in ('nan', 'None', ''):
                    continue
                holder = str(row.get('股东名称', '')).strip()
                changes_q2.append({
                    "holder_name": holder[:35] if holder and holder not in ('nan', 'None') else '',
                    "change_type": change_type,
                    "shares": _safe_float(row.get('持股数量') or row.get('股份数量')),
                    "ratio_pct": _safe_float(row.get('持股比例') or row.get('占流通股比例')),
                    "market_value": _safe_float(row.get('持股市值') or row.get('股份市值')),
                    "announce_date": ann_date,
                    "rank": _safe_float(row.get('排名')),
                    "relation": str(row.get('与上市公司关系', '')),
                    "method": str(row.get('方式', '')),
                    "source": "i问财",
                })
                seen_dates_q2.add(ann_date)
        # 查询2有效记录多 → 用查询2；否则用查询1
        # 有效定义: 有change_type且有持股数量/比例（至少有数据）
        def _has_share_data(r):
            return bool(r.get('shares') or r.get('ratio_pct') or r.get('market_value'))
        changes_q2_has_data = [r for r in changes_q2 if _has_share_data(r)]
        if len(changes_q2_has_data) >= 2:
            # 查询2数据充足，只用查询2
            changes = changes_q2_has_data
        else:
            # 查询2数据不足，合并查询1+查询2
            changes = changes_q2  # 先加查询2（有名称的）
            for row in result1['datas']:
                change_type = str(row.get('持股变动类型', '') or row.get('变动方向', '')).strip()
                if not change_type or change_type in ('nan', 'None', ''):
                    continue
                ann_date = str(row.get('公告日期', row.get('发生日期', '')))
                if ann_date in seen_dates_q2:
                    continue  # 查询2已有该日期数据，跳过
                holder_name = str(row.get('股东名称', '')).strip()
                changes.append({
                    "holder_name": holder_name[:35] if holder_name and holder_name not in ('nan', 'None') else '',
                    "change_type": change_type,
                    "shares": _safe_float(row.get('持股数量') or row.get('股份数量')),
                    "ratio_pct": _safe_float(row.get('持股比例') or row.get('占流通股比例')),
                    "market_value": _safe_float(row.get('持股市值') or row.get('股份市值')),
                    "announce_date": ann_date,
                    "rank": _safe_float(row.get('排名')),
                    "relation": str(row.get('与上市公司关系', '')),
                    "method": str(row.get('方式', '')),
                    "source": "i问财",
                })
        return changes
    except Exception as e:
        return []


def build_structure(stock_code, market, findings, data_dir=None):
    """
    构建股权结构
    数据源优先级: i问财 > 东财F10 > AKShare
    """
    result = {
        'stock_code': stock_code,
        'company_profile': {},
        'structure': {},
        'top_shareholders': [],
        'circulate_shareholders': [],
        'subsidiaries': [],
        'related_parties': [],
        'actual_controller': None,
        'control_chain': [],
        'equity_penetration': [],
        'shareholder_changes': [],  # i问财特有字段
        'notes': [],
        'warnings': [],
    }

    # 1. 实控人: i问财优先，东财F10/AKShare兜底（带超时）
    try:
        result['actual_controller'] = _run_with_timeout(
            _fetch_actual_controller_iwencai, stock_code, timeout=30
        )
    except Exception as e:
        print(f"  ⚠️ i问财实控人查询失败: {e}")
        result['actual_controller'] = None
    
    if result['actual_controller'] is None:
        try:
            result['actual_controller'] = _run_with_timeout(
                _fetch_actual_controller_ak, stock_code, timeout=30
            )
        except Exception as e:
            print(f"  ⚠️ AKShare实控人查询失败: {e}")
    
    # 2. 股东持股变动（i问财特有，AKShare不提供）- 带超时
    try:
        result['shareholder_changes'] = _run_with_timeout(
            _fetch_shareholder_changes_iwencai, stock_code, timeout=30
        ) or []
    except Exception as e:
        print(f"  ⚠️ i问财股东变动查询失败: {e}")
        result['shareholder_changes'] = []
    
    # 3. AKShare数据 - 带超时
    if ak is not None:
        try:
            result['company_profile'] = _run_with_timeout(
                _fetch_company_profile_ak, stock_code, timeout=30
            ) or {}
        except Exception as e:
            print(f"  ⚠️ AKShare公司概况查询失败: {e}")
        
        try:
            result['top_shareholders'] = _run_with_timeout(
                _fetch_top_shareholders_ak, stock_code, timeout=30
            ) or []
        except Exception as e:
            print(f"  ⚠️ AKShare股东查询失败: {e}")
        
        try:
            result['circulate_shareholders'] = _run_with_timeout(
                _fetch_circulate_shareholders_ak, stock_code, timeout=30
            ) or []
        except Exception as e:
            print(f"  ⚠️ AKShare流通股东查询失败: {e}")
    
    # 4. 从公告推断结构（补充）
    announcements = findings.get('announcements', {}).get('recent_30', [])
    related_deals = findings.get('related', {}).get('deals', [])
    subsidiary_ipo = findings.get('subsidiary', {}).get('subsidiaries', [])
    
    # 5. 子公司信息
    result['subsidiaries'] = _extract_subsidiaries(subsidiary_ipo, announcements)
    
    # 6. 关联方信息
    result['related_parties'] = _extract_related_parties(related_deals, announcements, stock_code)
    
    # 7. 股权穿透分析（返回穿透数据+治理预警）
    try:
        penetration, warnings = _analyze_equity_penetration(
            stock_code,
            result['top_shareholders'],
            result['actual_controller']
        )
        result['equity_penetration'] = penetration
        result['warnings'].extend(warnings)
    except Exception as e:
        print(f"  ⚠️ 股权穿透分析失败: {e}")
    
    # 8. 构建结构树
    result['structure'] = _build_structure_tree(
        stock_code, 
        result['top_shareholders'],
        result['subsidiaries'],
        result['related_parties'],
        result['actual_controller']
    )
    
    # 9. 生成结构文本
    result['text'] = _render_structure_text(result)
    
    # 10. 保存
    if data_dir:
        import os
        os.makedirs(data_dir, exist_ok=True)
        with open(os.path.join(data_dir, "structure.json"), "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    
    return result


def _fetch_top_shareholders_ak(stock_code):
    """AKShare: 前十大股东（取流通股东最新报告期）"""
    if ak is None:
        return []
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_circulate_stock_holder(symbol=code)
        if df is None or df.empty:
            return []
        # 取最新报告期
        dates = sorted(df['截止日期'].unique())
        if not dates:
            return []
        latest_date = dates[-1]
        df_latest = df[df['截止日期'] == latest_date]
        result = []
        for _, row in df_latest.iterrows():
            ratio = row.get('占流通股比例')
            # 过滤无效数据
            if ratio is None or str(ratio) == 'nan' or str(ratio) == '':
                continue
            result.append({
                "name": str(row.get("股东名称", ""))[:35],
                "ratio_pct": _safe_float(ratio),
                "shares": _safe_float(row.get("持股数量", 0)),
                "type": str(row.get("股本性质", "未知")),
                "date": str(latest_date),
            })
        return result[:10]
    except Exception as e:
        return []


def _fetch_company_profile_ak(stock_code):
    """AKShare: 公司基本信息"""
    if ak is None:
        return {}
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_profile_cninfo(symbol=code)
        if df is None or df.empty:
            return {}
        row = df.iloc[0]
        return {
            "name": str(row.get("公司名称", "")),
            "legal_representative": str(row.get("法人代表", "")),
            "industry": str(row.get("所属行业", "")),
            "listing_date": str(row.get("上市日期", "")),
        }
    except Exception as e:
        return {}


def _fetch_circulate_shareholders_ak(stock_code):
    """AKShare: 流通股东（取最新报告期）"""
    if ak is None:
        return []
    try:
        code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        df = ak.stock_circulate_stock_holder(symbol=code)
        if df is None or df.empty:
            return []
        # 取最新报告期
        dates = sorted(df['截止日期'].unique())
        if not dates:
            return []
        latest_date = dates[-1]
        df_latest = df[df['截止日期'] == latest_date]
        result = []
        for _, row in df_latest.iterrows():
            ratio = row.get('占流通股比例')
            # 过滤无效数据
            if ratio is None or str(ratio) == 'nan' or str(ratio) == '':
                continue
            result.append({
                "name": str(row.get("股东名称", ""))[:35],
                "ratio_pct": _safe_float(ratio),
                "shares": _safe_float(row.get("持股数量", 0)),
                "type": str(row.get("股本性质", "")),
                "date": str(latest_date),
            })
        return result[:10]
    except Exception as e:
        return []


def _fetch_actual_controller_em_f10(stock_code):
    """东财F10: 获取最新实控人（优先级最高的数据源）
    
    数据时效性优于CNINFO的stock_hold_control_cninfo，
    因为东财F10会持续更新。
    
    Returns:
        dict with keys: name, source, ratio_pct, control_type
        or None if not available
    """
    import requests as _req
    code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    # 东财F10用SZ/SH前缀
    if code.startswith('6') or code.startswith('68'):
        sec_code = f"SH{code}"
    else:
        sec_code = f"SZ{code}"
    
    try:
        api_url = 'https://datacenter.eastmoney.com/securities/api/data/v1/get'
        params = {
            'reportName': 'RPT_F10_BASIC_ORGINFO',
            'columns': 'ALL',
            'filter': f'(SECURITY_CODE="{code}")',
            'pageNumber': 1, 'pageSize': 1,
            'sortTypes': -1, 'sortColumns': 'SECURITY_CODE',
            'uniqueColumn': 'SECURITY_CODE',
            'source': 'HSF10', 'client': 'PC',
        }
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        r = _req.get(api_url, params=params, headers=headers, timeout=10)
        data = r.json()
        if data.get('result') and data['result'].get('data'):
            row = data['result']['data'][0]
            actual_holder = str(row.get('ACTUAL_HOLDER', ''))
            if actual_holder and actual_holder != 'None' and actual_holder != '无':
                return {
                    "name": actual_holder,
                    "source": "东财F10",
                    "ratio_pct": None,  # F10不提供控股比例
                    "control_type": "",
                }
            else:
                # 明确返回"无实控人"，而非None
                return {
                    "name": "无",
                    "source": "东财F10",
                    "ratio_pct": None,
                    "control_type": "",
                    "no_controller": True,
                }
    except Exception as e:
        record_result(__name__, '_fetch_actual_controller_em_f10', e, note='静默降级')
        pass
    
    return None


def _fetch_actual_controller_ak(stock_code):
    """获取实际控制人
    
    数据源优先级（按时效性排序）:
    1. 东财F10 (RPT_F10_BASIC_ORGINFO) — 最新的公司资料
    2. 中证信披 (stock_hold_control_cninfo) — 可能有穿透链
    3. 公司简介 (stock_profile_cninfo)
    4. 第一大股东推断 (持股>30%)
    
    注意：中证信披数据可能严重滞后（如002259停在2018-12-31），
    当东财F10返回"无实控人"时，中证信披的历史数据不应覆盖。
    """
    code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    
    # 1. 东财F10（最高优先级）
    em_result = _fetch_actual_controller_em_f10(stock_code)
    if em_result is not None:
        return em_result
    
    if ak is None:
        return None
    
    # 2. 中证信披API（可提供穿透链，但数据可能滞后）
    try:
        df = ak.stock_hold_control_cninfo()
        if df is not None and not df.empty:
            df_filtered = df[df['证券代码'] == code]
            if not df_filtered.empty:
                row = df_filtered.iloc[0]
                controller_name = str(row.get('实际控制人名称', ''))
                if controller_name and controller_name != '无':
                    return {
                        "name": controller_name,
                        "ratio_pct": _safe_float(row.get('控股比例', 0)),
                        "source": "中证信披",
                        "control_type": str(row.get('控制类型', '')),
                    }
    except Exception as e:
        record_result(__name__, '_fetch_actual_controller_ak', e, note='静默降级')
        pass
    
    # 3. 从公司简介获取
    try:
        df = ak.stock_profile_cninfo(symbol=code)
        if df is not None and not df.empty:
            row = df.iloc[0]
            controller = str(row.get("实际控制人", ""))
            if controller and controller != "nan":
                return {
                    "name": controller,
                    "source": "公司简介",
                }
    except Exception as e:
        record_result(__name__, '_fetch_actual_controller_ak', e, note='静默降级')
        pass
    
    # 4. 从第一大股东推断
    holders = _fetch_top_shareholders_ak(stock_code)
    if holders:
        top1 = holders[0]
        ratio = top1.get("ratio_pct", 0)
        if ratio > 30:
            return {
                "name": top1.get("name", ""),
                "ratio_pct": ratio,
                "source": "第一大股东推断",
            }
    
    return None


def _controller_in_shareholders(controller_name, shareholders):
    """检查实控人是否出现在当前股东名单中
    
    Args:
        controller_name: 实控人名称
        shareholders: 股东列表，每项有'name'字段
    
    Returns:
        tuple: (found: bool, matched_name: str or None)
    """
    if not controller_name or controller_name == '无':
        return False, None
    
    ctrl = controller_name.strip()
    for sh in shareholders:
        name = sh.get('name', '').strip()
        if not name:
            continue
        # 精确匹配或包含匹配
        if ctrl == name or ctrl in name or name in ctrl:
            return True, name
    return False, None


def _analyze_equity_penetration(stock_code, top_shareholders, actual_controller):
    """股权穿透分析（含多层穿透 + 实控人交叉验证 + 治理预警）
    
    核心逻辑：
    1. 获取穿透链（中证信披可提供多层穿透）
    2. 交叉验证：实控人是否仍在当前股东名单中
    3. 多源一致确认：东财F10说"无" + 实控人不在十大股东 = 确认已退出
    4. 治理预警：无实控人 / 实控人与第一大股东冲突
    """
    penetration = []
    warnings = []
    
    # 判断是否为"无实控人"
    is_no_controller = (actual_controller is not None and 
                        actual_controller.get('no_controller', False))
    ctrl_name = actual_controller.get('name', '') if actual_controller else ''
    ctrl_source = actual_controller.get('source', '') if actual_controller else ''
    
    # 1. 穿透链：从中证信披获取（即使东财F10说"无"，也保留历史穿透作为参考）
    cninfo_ctrl_name = None
    cninfo_ctrl_ratio = 0
    if ak is not None:
        try:
            df_cninfo = ak.stock_hold_control_cninfo()
            if df_cninfo is not None and not df_cninfo.empty:
                code = stock_code.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
                df_filtered = df_cninfo[df_cninfo['证券代码'] == code]
                if not df_filtered.empty:
                    row = df_filtered.iloc[0]
                    ultimate_controller = str(row.get('实际控制人名称', ''))
                    direct_controller = str(row.get('直接控制人名称', ''))
                    cninfo_ctrl_name = ultimate_controller
                    cninfo_ctrl_ratio = _safe_float(row.get('控股比例', 0)) or 0
                    control_type = str(row.get('控制类型', ''))
                    
                    if ultimate_controller and ultimate_controller != '无':
                        # 标注为历史数据（如果东财F10已确认无实控人）
                        source_label = "中证信披(历史)" if is_no_controller else "中证信披"
                        penetration.append({
                            "level": 0,
                            "entity": ultimate_controller,
                            "type": "最终实际控制人",
                            "ratio": cninfo_ctrl_ratio,
                            "note": f"控制类型: {control_type}",
                            "source": source_label,
                            "stale": is_no_controller,
                        })
                    
                    if direct_controller and direct_controller != ultimate_controller:
                        source_label = "中证信披(历史)" if is_no_controller else "中证信披"
                        penetration.append({
                            "level": 1,
                            "entity": direct_controller,
                            "type": "直接控制人",
                            "ratio": cninfo_ctrl_ratio,
                            "note": "直接持股主体",
                            "source": source_label,
                            "stale": is_no_controller,
                        })
        except Exception as _sexc:
            record(__name__, '_analyze_equity_penetration', _sexc, note='静默降级')
            pass
    
    # 2. 如果中证信披无数据，使用东财F10/推断的实控人
    if not penetration and actual_controller and not is_no_controller:
        penetration.append({
            "level": 0,
            "entity": ctrl_name,
            "type": "实际控制人",
            "ratio": actual_controller.get("ratio_pct", "N/A"),
            "note": f"来源: {ctrl_source}",
            "source": ctrl_source,
            "stale": False,
        })
    
    # 3. 前十大股东（level 2）
    for i, sh in enumerate(top_shareholders[:5], 1):
        penetration.append({
            "level": 2,
            "entity": sh.get("name", ""),
            "type": "股东",
            "ratio": sh.get("ratio_pct", 0),
            "note": f"第{i}大股东",
            "source": "AKShare",
            "stale": False,
        })
    
    # 4. 交叉验证：实控人是否仍在当前股东名单中
    if cninfo_ctrl_name and cninfo_ctrl_name != '无':
        found, matched_name = _controller_in_shareholders(cninfo_ctrl_name, top_shareholders)
        if not found:
            warnings.append(
                f"⚠️ 中证信披登记的实控人\"{cninfo_ctrl_name}\"({cninfo_ctrl_ratio}%)"
                f"不在当前前十大股东名单中，可能已退出。"
                f"(东财F10确认: {'无实控人' if is_no_controller else '未知'})"
            )
        elif is_no_controller:
            # 名字能匹配但东财F10说无实控人 → 可能是关联方代持
            warnings.append(
                f"⚠️ 中证信披实控人\"{cninfo_ctrl_name}\"仍在前十大股东中，"
                f"但东财F10显示无实控人，控制关系可能已变更"
            )
    
    # 5. 无实控人预警
    if is_no_controller:
        top1 = top_shareholders[0] if top_shareholders else {}
        top1_name = top1.get('name', '未知')
        top1_ratio = top1.get('ratio_pct', 0)
        if top1_ratio and top1_ratio > 20:
            warnings.append(
                f"⚠️ 公司无实际控制人，第一大股东\"{top1_name}\"({top1_ratio:.2f}%)"
                f"持股比例较高但未登记为实控人，存在治理不确定性"
            )
    else:
        # 6. 实控人与第一大股东对比（仅在有实控人时）
        top1_ratio = top_shareholders[0].get('ratio_pct', 0) if top_shareholders else 0
        ctrl_ratio = 0
        for p in penetration:
            if p.get('stale'):
                continue  # 跳过已退出的历史数据
            r = p.get('ratio', 0)
            if isinstance(r, (int, float)) and r > 0:
                ctrl_ratio = max(ctrl_ratio, r)
        
        if top1_ratio and ctrl_ratio and isinstance(top1_ratio, (int, float)) and isinstance(ctrl_ratio, (int, float)):
            if top1_ratio > ctrl_ratio + 2:
                warnings.append(
                    f"⚠️ 第一大股东({top1_ratio:.2f}%)持股已显著超过实控人({ctrl_ratio:.2f}%)，控制权可能已变更"
                )
    
    return penetration, warnings


def _extract_subsidiaries(subsidiary_ipo, announcements):
    """从公告提取子公司信息"""
    subsidiaries = []
    
    # 从分拆上市公告提取
    for sub in subsidiary_ipo:
        name = sub.get('sub_company', '未知子公司')
        if name != '未知':
            subsidiaries.append({
                'name': name,
                'type': '拟分拆上市',
                'status': sub.get('status', ''),
                'detail': sub,
            })
    
    # 从公告标题提取
    for a in announcements[:50]:
        title = a.get('title', '')
        # 模式："关于子公司XXX的公告"
        m = re.search(r'关于子公司?([^的]{2,20}公司)的', title)
        if m:
            name = m.group(1)
            if not any(s['name'] == name for s in subsidiaries):
                subsidiaries.append({
                    'name': name,
                    'type': '子公司',
                    'status': '',
                    'detail': title,
                })
    
    return subsidiaries[:20]


def _extract_related_parties(related_deals, announcements, stock_code):
    """从公告提取关联方信息"""
    related = []
    seen = set()
    
    # 从关联交易提取
    for deal in related_deals[:30]:
        title = deal.get('title', '')
        # 提取关联方名称
        m = re.search(r'关于(.{2,20}公司)', title)
        if m:
            name = m.group(1)
            if name not in seen and stock_code not in name:
                seen.add(name)
                related.append({
                    'name': name,
                    'deal_type': deal.get('type', ''),
                    'detail': title,
                    'date': deal.get('date', ''),
                })
    
    # 从公告标题提取
    for a in announcements[:50]:
        title = a.get('title', '')
        if '关联交易' in title or '关联方' in title:
            m = re.search(r'关于(.{2,20}公司)', title)
            if m:
                name = m.group(1)
                if name not in seen and stock_code not in name:
                    seen.add(name)
                    related.append({
                        'name': name,
                        'deal_type': '关联交易',
                        'detail': title,
                        'date': a.get('date', ''),
                    })
    
    return related[:20]


def _build_structure_tree(stock_code, top_sh, subsidiaries, related, controller):
    """构建股权结构树"""
    structure = {
        'main_listed': {
            'name': stock_code,
            'type': '上市公司',
            'children': subsidiaries,
            'related': related,
        },
        'shareholders': top_sh,
    }
    
    if controller:
        structure['actual_controller'] = controller
    
    return structure


def _render_structure_text(result):
    """渲染结构文本图"""
    lines = []
    lines.append("## 股权结构图\n")
    lines.append("=" * 50)
    
    # 公司基本信息
    profile = result.get('company_profile', {})
    if profile:
        lines.append(f"\n### 公司: {profile.get('name', '')}")
        if profile.get('industry'):
            lines.append(f"- 行业: {profile['industry']}")
    
    lines.append(f"\n### 【上市公司】{result.get('stock_code', '')}\n")
    
    # 股权穿透
    penetration = result.get('equity_penetration', [])
    if penetration:
        lines.append("**股权穿透**:")
        for p in penetration:
            indent = "  " * p.get('level', 0)
            ratio = p.get('ratio', 'N/A')
            ratio_str = f"{ratio}%" if isinstance(ratio, (int, float)) else str(ratio)
            stale_tag = " [已退出]" if p.get('stale') and '[已退出]' not in p.get('note', '') else ""
            lines.append(f"{indent}→ {p.get('entity', '')} [{ratio_str}] ({p.get('note', '')}){stale_tag}")
        lines.append("")
    
    # 股东结构
    shareholders = result.get('top_shareholders', [])
    if shareholders:
        lines.append("**前十大股东**:")
        lines.append("| 股东名称 | 持股比例 | 股东性质 |")
        lines.append("|----------|---------|---------|")
        for sh in shareholders[:5]:
            lines.append(f"| {sh.get('name', '?')[:20]} | {sh.get('ratio_pct', '?')}% | {sh.get('type', '?')} |")
        lines.append("")
    
    # 实控人
    ctrl = result.get('actual_controller')
    if ctrl:
        if ctrl.get('no_controller'):
            lines.append(f"**实际控制人**: 无 (来源: {ctrl.get('source', '')}，当前无实控人)")
        else:
            lines.append(f"**实际控制人**: {ctrl.get('name', '')} (来源: {ctrl.get('source', '')})")
        lines.append("")
    
    # 子公司
    structure = result.get('structure', {})
    main = structure.get('main_listed', {})
    children = main.get('children', [])
    if children:
        lines.append("**子公司/拟分拆资产**:")
        for child in children[:10]:
            lines.append(f"  - {child.get('name', '')} [{child.get('type', '')}]")
        lines.append("")
    
    # 治理预警
    warnings = result.get('warnings', [])
    if warnings:
        lines.append("**⚠️ 治理预警**:")
        for w in warnings:
            lines.append(f"  - {w}")
        lines.append("")
    
    # 关联方
    related = main.get('related', [])
    if related:
        lines.append("**关联方资本运作**:")
        for rel in related[:10]:
            lines.append(f"  - {rel.get('name', '')} [{rel.get('deal_type', '')}]")
    
    return '\n'.join(lines)


def _safe_float(value, default=None):
    """安全转换为float"""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


if __name__ == '__main__':
    result = build_structure('000001', 'a', {})
    print(result['text'])


def generate_report_section(data: dict) -> list:
    lines = []
    lines.append("## 股权结构分析")
    lines.append("")
    text = data.get('text', '')
    if text:
        lines.append("```")
        lines.append(text)
        lines.append("```")
        lines.append("")
    else:
        lines.append("> 股权结构信息有限，需结合年报或工商信息补充。")
        lines.append("")

    # 通达信股本结构增强数据
    tdx_struct = data.get('tdx_structure', {})
    if tdx_struct and tdx_struct.get('latest'):
        latest = tdx_struct.get('latest', {})
        history = tdx_struct.get('history', [])

        lines.append("### 股本结构详情（通达信）")
        lines.append("")

        latest_date = latest.get('date', '')
        total_shares = latest.get('total_shares', '')
        tradable = latest.get('tradable_shares', '')
        non_tradable = latest.get('non_tradable_shares', '')

        if latest_date:
            lines.append(f'**最新数据日期**：{latest_date}')
        if total_shares:
            total_str = f'{total_shares:,}' if isinstance(total_shares, (int, float)) else str(total_shares)
            lines.append(f'**总股本**：{total_str} 股')
        if tradable:
            tradable_str = f'{tradable:,}' if isinstance(tradable, (int, float)) else str(tradable)
            lines.append(f'**流通股**：{tradable_str} 股')
        if non_tradable:
            non_tradable_str = f'{non_tradable:,}' if isinstance(non_tradable, (int, float)) else str(non_tradable)
            lines.append(f'**限售股**：{non_tradable_str} 股')

        lines.append('')

        if history and len(history) > 1:
            lines.append('**近期股本变化**：')
            lines.append('')
            lines.append('| 日期 | 总股本 | 流通股 | 限售股 |')
            lines.append('|------|--------|--------|--------|')
            for item in history:
                date = item.get('date', '')
                total = item.get('total_shares', '')
                trad = item.get('tradable_shares', '')
                non_trad = item.get('non_tradable_shares', '')
                total_s = f'{total:,}' if isinstance(total, (int, float)) else str(total)
                trad_s = f'{trad:,}' if isinstance(trad, (int, float)) else str(trad)
                non_trad_s = f'{non_trad:,}' if isinstance(non_trad, (int, float)) else str(non_trad)
                lines.append(f'| {date} | {total_s} | {trad_s} | {non_trad_s} |')
            lines.append('')

        lines.append('*数据来源：通达信官方数据接口（TDX API）*')
        lines.append("")

    return lines
