#!/usr/bin/env python3
"""
CNKI 知网文献爬虫 - Selenium 版 (Edge)
直接在终端运行 python cnki_crawler.py 即可
"""

import sys, os, io, subprocess

# ===== 自动创建 & 激活虚拟环境（完全便携） =====
_script_dir = os.path.dirname(os.path.abspath(__file__))
_venv_dir = os.path.join(_script_dir, 'venv')
_venv_python = os.path.join(_venv_dir, 'Scripts', 'python.exe')

if not os.path.isfile(_venv_python):
    print("[设置] 正在创建虚拟环境...")
    subprocess.check_call([sys.executable, "-m", "venv", _venv_dir])
    print("[设置] 虚拟环境已创建，正在安装依赖...")

if sys.executable.lower() != _venv_python.lower():
    subprocess.check_call([_venv_python, "-m", "pip", "install", "--upgrade", "pip", "-q"])
    for _pkg in ['selenium', 'webdriver-manager', 'pandas', 'openpyxl', 'lxml']:
        subprocess.check_call([_venv_python, "-m", "pip", "install", _pkg, "-q"])
    print("[设置] 依赖安装完成，启动程序...")
    os.execv(_venv_python, [_venv_python] + sys.argv)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import time, re, random, uuid, pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.edge.service import Service as EdgeService

# ==================== 配置 ====================
OUTPUT_DIR = ""
MAX_RESULTS = 0

# ==================== 初始化浏览器 ====================

def setup_driver():
    """初始化 Edge WebDriver"""
    options = webdriver.EdgeOptions()
    options.add_argument('--disable-gpu')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-software-rasterizer')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)
    profile_id = uuid.uuid4().hex[:8]
    options.add_argument(f'--user-data-dir={os.environ.get("TEMP", "/tmp")}/cnki_edge_{profile_id}')
    options.add_argument('--start-maximized')

    try:
        from webdriver_manager.microsoft import EdgeChromiumDriverManager
        service = EdgeService(EdgeChromiumDriverManager().install())
    except:
        service = EdgeService()

    driver = webdriver.Edge(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver


def safe_find(driver, by, selector, timeout=3):
    try:
        return WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, selector)))
    except:
        return None


def safe_find_all(driver, by, selector, timeout=3):
    try:
        WebDriverWait(driver, timeout).until(
            EC.presence_of_element_located((by, selector)))
        return driver.find_elements(by, selector)
    except:
        return []


# ==================== 核心功能 ====================

def wait_for_user_search(driver):
    """打开知网，让用户手动搜索，等待用户按 Enter 后开始爬取"""
    print("=" * 60)
    print("   请在弹出的 Edge 浏览器中完成以下操作：")
    print("   1. 在知网页面中设置你的检索条件")
    print("   2. 如果出现滑块验证码，手动通过")
    print("   3. 点击「检索」按钮，进入结果页面")
    print("   4. 回到此终端，按 Enter 键开始自动爬取")
    print("=" * 60)

    driver.get("https://kns.cnki.net/kns8/AdvSearch?classid=YSTT4HG0")
    time.sleep(3)

    # 检测验证码
    if 'verify' in driver.current_url or '安全验证' in driver.page_source:
        print("\n[!] 检测到安全验证，请在浏览器中完成滑块验证...")
        start = time.time()
        while time.time() - start < 300:
            if 'verify' not in driver.current_url and '安全验证' not in driver.page_source:
                print("[OK] 验证通过！")
                break
            time.sleep(2)

    # 等待用户手动搜索
    input("\n请完成搜索后，按 Enter 键开始自动爬取...")

    time.sleep(3)
    print("[开始] 正在解析搜索结果...")
    return True


def parse_row(row_el):
    """解析结果行"""
    result = {'title': '', 'authors': '', 'source': '', 'date': '', 'cited': '0', 'detail_url': ''}
    try:
        links = row_el.find_elements(By.CSS_SELECTOR, 'a[href*="Detail"], a[href*="detail"], a.fz14')
        if links:
            result['title'] = links[0].text.strip()
            result['detail_url'] = links[0].get_attribute('href') or ''
        if not result['title']:
            result['title'] = row_el.text.strip().split('\n')[0]

        full_text = row_el.text.strip()
        m = re.search(r'被引\s*(\d+)', full_text)
        if m:
            result['cited'] = m.group(1)
    except:
        pass
    return result


def get_detail(driver, url):
    """打开详情页提取摘要和关键词"""
    if not url or 'javascript' in url:
        return {'keywords': '', 'abstract': ''}

    result = {'keywords': '', 'abstract': ''}
    orig = driver.current_window_handle
    try:
        driver.execute_script(f"window.open('{url}', '_blank');")
        time.sleep(1)
        driver.switch_to.window(driver.window_handles[-1])
        time.sleep(2)

        # 摘要
        for sel in ['//span[contains(@id, "ChDivSummary")]',
                     '//div[contains(@class, "abstract")]',
                     '#ChDivSummary', '[class*="abstract"]']:
            try:
                el = driver.find_element(By.XPATH, sel) if sel.startswith('/') else driver.find_element(By.CSS_SELECTOR, sel)
                t = el.text.strip()
                if t and len(t) > 10:
                    result['abstract'] = t
                    break
            except:
                continue

        # 关键词
        for sel in ['//span[contains(@id, "catalog_KEYWORD")]',
                     '//label[contains(text(), "关键词")]/following::*',
                     '[class*="keyword"]']:
            try:
                if sel.startswith('/'):
                    els = driver.find_elements(By.XPATH, sel)
                else:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                for el in els:
                    t = el.text.strip()
                    if t and len(t) > 2 and '关键词' not in t:
                        result['keywords'] = re.sub(r'[;；]', '; ', t)
                        break
                if result['keywords']:
                    break
            except:
                continue

        driver.close()
        driver.switch_to.window(orig)
    except:
        try:
            if len(driver.window_handles) > 1:
                driver.close()
            driver.switch_to.window(orig)
        except:
            pass
    return result


def save_excel(data, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pd.DataFrame(data).to_excel(path, index=False, engine='openpyxl')
    print(f"  [保存] {len(data)} 条 -> {path}")


# ==================== 主流程 ====================

def main():
    global OUTPUT_DIR, MAX_RESULTS

    # 交互设置
    print("=" * 60)
    print("   CNKI 知网文献爬虫")
    print("=" * 60)
    default_dir = os.path.join(os.environ.get('USERPROFILE', 'C:/'), 'Desktop', 'CNKI_结果')
    d = input(f"保存目录（默认: {default_dir}）: ").strip()
    OUTPUT_DIR = d if d else default_dir
    m = input("最多下载篇数（0=全部，默认0）: ").strip()
    MAX_RESULTS = int(m) if m.isdigit() else 0

    # 启动浏览器
    print("\n[启动] 正在打开 Edge 浏览器...")
    try:
        driver = setup_driver()
    except Exception as e:
        print(f"[失败] 浏览器启动失败: {e}")
        return

    all_papers = []
    try:
        if not wait_for_user_search(driver):
            return

        # 解析总页数
        total_pages = 1
        # 策略1: 查找分页信息文本
        for sel in ['.pagination', '.page-box', '.page-info', '[class*="page"]',
                     '.page-nav', '#page_num', '.total-count']:
            el = safe_find(driver, By.CSS_SELECTOR, sel, 2)
            if el:
                text = el.text.strip()
                nums = re.findall(r'/(\d+)', text) or re.findall(r'共(\d+)页', text) or re.findall(r'(\d+)页', text)
                if nums:
                    total_pages = max(int(n) for n in nums)
                    break

        # 策略2: 数页码按钮
        if total_pages == 1:
            try:
                page_btns = driver.find_elements(By.XPATH, '//a[regex:test(text(), "^\d+$")]')
            except:
                page_btns = []
            if not page_btns:
                try:
                    page_btns = driver.find_elements(By.CSS_SELECTOR, '.pagination a, .page-box a, [class*="page"] a')
                    page_btns = [a for a in page_btns if a.text.strip().isdigit()]
                except:
                    page_btns = []
            if page_btns:
                nums = [int(a.text.strip()) for a in page_btns if a.text.strip().isdigit()]
                total_pages = max(nums) if nums else 1

        print(f"[共 {total_pages} 页结果]")

        current = 1
        max_pages = total_pages
        if MAX_RESULTS > 0:
            max_pages = min(total_pages, (MAX_RESULTS + 19) // 20)

        while current <= max_pages:
            print(f"\n[第{current}/{max_pages}页] 正在处理...")
            time.sleep(2)

            # 获取结果行
            rows = safe_find_all(driver, By.CSS_SELECTOR,
                'table.GridTableContent tr, .result-table tr, .list-table tbody tr')
            if len(rows) <= 1:
                rows = safe_find_all(driver, By.TAG_NAME, 'tr')

            paper_list = []
            data_rows = rows[1:] if len(rows) > 1 else rows
            for row in data_rows:
                info = parse_row(row)
                if info['title']:
                    lines = [l.strip() for l in row.text.strip().split('\n') if l.strip()]
                    info['authors'] = lines[1] if len(lines) > 1 else ''
                    info['source'] = lines[2] if len(lines) > 2 else ''
                    info['date'] = lines[3] if len(lines) > 3 else ''
                    paper_list.append(info)
                    print(f"  [{len(paper_list)}] {info['title'][:50]}")

            if not paper_list:
                print("  [!] 未解析到论文，可能页面结构已变")
                # 保存当前数据后退出
                break

            # 提取详情
            print(f"  [提取] 获取摘要和关键词...")
            for i, p in enumerate(paper_list):
                det = get_detail(driver, p.get('detail_url', ''))
                p['keywords'] = det.get('keywords', '')
                p['abstract'] = det.get('abstract', '')
                print(f"    [{i+1}/{len(paper_list)}] {p['title'][:30]}")
                if i < len(paper_list) - 1:
                    time.sleep(8)

                if MAX_RESULTS > 0 and len(all_papers) + i + 1 >= MAX_RESULTS:
                    break

            all_papers.extend(paper_list)
            save_excel(all_papers, os.path.join(OUTPUT_DIR, 'cnki_results.xlsx'))
            print(f"  [进度] 共 {len(all_papers)} 条")

            if MAX_RESULTS > 0 and len(all_papers) >= MAX_RESULTS:
                print(f"[完成] 已达 {MAX_RESULTS} 条")
                break

            # 翻页：多种策略
            if current < max_pages:
                next_found = False

                # 策略1: 点击"下一页"文字链接
                for xp in ['//a[contains(text(), "下一页")]',
                           '//span[contains(text(), "下一页")]',
                           '//button[contains(text(), "下一页")]',
                           '//a[contains(@class, "next")]',
                           '//li[contains(@class, "next")]/a',
                           '//div[contains(@class, "page")]//a[contains(text(),">")]',
                           '//div[contains(@class, "page")]//span[contains(text(),">")]']:
                    try:
                        el = driver.find_element(By.XPATH, xp)
                        if el.is_displayed():
                            driver.execute_script("arguments[0].click();", el)
                            next_found = True
                            break
                    except:
                        continue

                # 策略2: CSS 选择器
                if not next_found:
                    for css in ['.pagination .next', 'a.next', '.next-page',
                                'li.next a', '.page-box .next', '[class*="next"] a',
                                '.page-nav a:last-child', '.pagination a:last-child']:
                        try:
                            el = driver.find_element(By.CSS_SELECTOR, css)
                            if el.is_displayed():
                                driver.execute_script("arguments[0].click();", el)
                                next_found = True
                                break
                        except:
                            continue

                # 策略3: 找页码链接，点击当前页+1
                if not next_found:
                    try:
                        page_links = driver.find_elements(By.XPATH, '//a[regex:test(text(), "^\d+$")]')
                    except:
                        page_links = []
                    if not page_links:
                        try:
                            page_links = driver.find_elements(By.CSS_SELECTOR, '.pagination a, .page-box a, [class*="page"] a')
                            page_links = [a for a in page_links if a.text.strip().isdigit()]
                        except:
                            page_links = []
                    if page_links:
                        nums = []
                        for a in page_links:
                            try:
                                nums.append((int(a.text.strip()), a))
                            except:
                                pass
                        nums.sort()
                        for n, a in nums:
                            if n == current + 1:
                                driver.execute_script("arguments[0].click();", a)
                                next_found = True
                                break

                # 策略4: 通过 URL 直接跳转
                if not next_found:
                    try:
                        cur_url = driver.current_url
                        if 'curpage=' in cur_url:
                            new_url = re.sub(r'curpage=\d+', f'curpage={current+1}', cur_url)
                        elif '&pageno=' in cur_url:
                            new_url = re.sub(r'pageno=\d+', f'pageno={current+1}', cur_url)
                        elif '?' in cur_url:
                            new_url = cur_url + f'&curpage={current+1}'
                        else:
                            new_url = cur_url + f'?curpage={current+1}'
                        driver.get(new_url)
                        next_found = True
                        time.sleep(3)
                    except:
                        pass

                if not next_found:
                    print("  [!] 无法翻页，已停止")
                    break
                time.sleep(4)
                current += 1
                # 翻页后检查验证码
                if 'verify' in driver.current_url or '安全验证' in driver.page_source:
                    print("\n[!] 翻页触发验证码，请在浏览器中完成...")
                    start = time.time()
                    while time.time() - start < 300:
                        if 'verify' not in driver.current_url and '安全验证' not in driver.page_source:
                            print("[OK] 验证通过！")
                            break
                        time.sleep(2)
            else:
                break

        save_excel(all_papers, os.path.join(OUTPUT_DIR, 'cnki_results.xlsx'))
        print(f"\n{'='*60}")
        print(f"[完成] 共 {len(all_papers)} 条文献")
        print(f"[路径] {os.path.join(OUTPUT_DIR, 'cnki_results.xlsx')}")

    except KeyboardInterrupt:
        print("\n[!] 中断")
        if all_papers:
            save_excel(all_papers, os.path.join(OUTPUT_DIR, 'cnki_results_partial.xlsx'))
    except Exception as e:
        print(f"\n[ERR] {e}")
        import traceback; traceback.print_exc()
        if all_papers:
            save_excel(all_papers, os.path.join(OUTPUT_DIR, 'cnki_results_error.xlsx'))
    finally:
        try:
            driver.quit()
        except:
            pass


if __name__ == '__main__':
    main()
