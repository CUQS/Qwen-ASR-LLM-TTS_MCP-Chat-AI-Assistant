import requests
from bs4 import BeautifulSoup


def get_yahoo_weather():
    """
    获取东京都东久留米市（Higashikurume）的雅虎天气预报。
    基于最新的 yjw_pinpoint 页面结构解析。
    """
    url = "https://weather.yahoo.co.jp/weather/jp/13/4410/13222.html"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        response.encoding = response.apparent_encoding

        soup = BeautifulSoup(response.text, 'html.parser')

        # 1. 提取区域和日期标题
        title_node = soup.find("div", id="yjw_pinpoint_today")
        if not title_node:
            return "未能解析到天气信息，页面结构可能已更改。"

        title_text = title_node.find("h3").get_text(strip=True) if title_node.find("h3") else "今日天气"

        # 2. 提取分时段天气表格 (yjw_table2)
        table = title_node.find("table", class_="yjw_table2")
        rows = table.find_all("tr")

        # 数据行解析：
        # rows[0]: 时间 (0时, 3时...)
        # rows[1]: 天气图标和文字
        # rows[2]: 气温
        # rows[3]: 湿度
        # rows[4]: 降水量

        times = [td.get_text(strip=True) for td in rows[0].find_all("td")][1:]  # 跳过标题列
        weathers = [td.get_text(strip=True) for td in rows[1].find_all("td")][1:]
        temps = [td.get_text(strip=True) for td in rows[2].find_all("td")][1:]
        precips = [td.get_text(strip=True) for td in rows[4].find_all("td")][1:]

        # 3. 提取警报/注意报 (如果有)
        warn_node = soup.find("div", id="wrnrpt")
        warning_text = "无特别警报"
        if warn_node:
            warn_items = warn_node.find_all("dd")
            if warn_items:
                warning_text = "、".join([item.get_text(strip=True) for item in warn_items])

        # 4. 组合输出
        forecast_details = []
        for i in range(len(times)):
            forecast_details.append(f"{times[i]}: {weathers[i]} ({temps[i]}℃, 降水{precips[i]}mm)")

        result = (
            f"📍 【{title_text}】\n"
            f"⚠️ 警报/注意报: {warning_text}\n"
            f"--- 3小时预报 ---\n"
            + "\n".join(forecast_details)
        )
        return result

    except Exception as e:
        return f"获取天气失败: {str(e)}"

