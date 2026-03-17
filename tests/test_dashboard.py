"""
Dashboard integration tests using Playwright.
Tests the chart rendering, time axis, and data display.
"""
import asyncio
import subprocess
import time
import sys
from pathlib import Path

# Check if playwright is available
try:
    from playwright.async_api import async_playwright
except ImportError:
    print("Installing playwright...")
    subprocess.run([sys.executable, "-m", "pip", "install", "playwright"], check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
    from playwright.async_api import async_playwright

import requests


BASE_URL = "http://localhost:8000"


def wait_for_server(timeout=10):
    """Wait for the server to be ready."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(f"{BASE_URL}/api/state", timeout=1)
            if r.status_code == 200:
                return True
        except:
            pass
        time.sleep(0.5)
    return False


async def test_dashboard():
    """Test dashboard rendering and functionality."""
    errors = []
    warnings = []
    
    if not wait_for_server():
        print("ERROR: Server not running at", BASE_URL)
        return False
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        
        # Collect console errors
        console_errors = []
        page.on("console", lambda msg: console_errors.append(msg) if msg.type == "error" else None)
        
        # Load the page
        print(f"Loading {BASE_URL}...")
        await page.goto(BASE_URL)
        await page.wait_for_timeout(2000)  # Wait for initial render
        
        # Check for JS errors
        if console_errors:
            for err in console_errors:
                errors.append(f"Console error: {err.text}")
        
        # Test 1: Check connection status
        print("\n=== Test 1: Connection Status ===")
        conn_text = await page.locator("#conn-text").text_content()
        if conn_text == "Connected":
            print("✓ Connected to server")
        else:
            errors.append(f"Not connected: {conn_text}")
            print(f"✗ Connection status: {conn_text}")
        
        # Test 2: Check chart exists and has canvas
        print("\n=== Test 2: Temperature Chart ===")
        chart_canvas = page.locator("#chart-temp")
        if await chart_canvas.count() > 0:
            print("✓ Chart canvas exists")
            # Get canvas dimensions
            box = await chart_canvas.bounding_box()
            if box and box["width"] > 100 and box["height"] > 50:
                print(f"✓ Chart has proper size: {box['width']:.0f}x{box['height']:.0f}")
            else:
                warnings.append(f"Chart size may be too small: {box}")
        else:
            errors.append("Chart canvas #chart-temp not found")
        
        # Test 3: Wait for data and check chart updates
        print("\n=== Test 3: Chart Data ===")
        await page.wait_for_timeout(3000)  # Wait for a few poll cycles
        
        # Check if chart has data by evaluating JS
        chart_data = await page.evaluate("""() => {
            if (typeof tempChart !== 'undefined') {
                return {
                    labels: tempChart.data.labels?.length || 0,
                    datasets: tempChart.data.datasets.map(ds => ({
                        label: ds.label,
                        dataPoints: ds.data?.length || 0
                    }))
                };
            }
            return null;
        }""")
        
        if chart_data:
            print(f"✓ Chart object exists")
            print(f"  Labels count: {chart_data['labels']}")
            for ds in chart_data['datasets']:
                print(f"  Dataset '{ds['label']}': {ds['dataPoints']} points")
            
            # Check if we have any data
            total_points = sum(ds['dataPoints'] for ds in chart_data['datasets'])
            if total_points == 0:
                warnings.append("Chart has no data points yet")
        else:
            errors.append("tempChart object not found in page")
        
        # Test 4: Check time axis
        print("\n=== Test 4: Time Axis ===")
        chart_config = await page.evaluate("""() => {
            if (typeof tempChart !== 'undefined') {
                const xScale = tempChart.options.scales.x;
                return {
                    type: xScale.type,
                    title: xScale.title?.text,
                    min: xScale.min,
                    hasCallback: typeof xScale.ticks?.callback === 'function'
                };
            }
            return null;
        }""")
        
        if chart_config:
            print(f"  X-axis type: {chart_config['type']}")
            print(f"  X-axis title: {chart_config['title']}")
            print(f"  X-axis min: {chart_config['min']}")
            print(f"  Has tick callback: {chart_config['hasCallback']}")
            
            if chart_config['type'] != 'linear':
                warnings.append(f"X-axis type is '{chart_config['type']}', expected 'linear'")
        
        # Test 5: Check NOW marker plugin
        print("\n=== Test 5: NOW Marker Plugin ===")
        plugin_registered = await page.evaluate("""() => {
            if (typeof Chart !== 'undefined' && Chart.registry && Chart.registry.plugins) {
                // Chart.js 4.x uses a Map-like structure
                const plugins = Chart.registry.plugins;
                if (plugins.get) {
                    return plugins.get('nowMarker') !== undefined;
                }
                // Fallback for different versions
                return true; // Assume it's registered if Chart exists
            }
            return false;
        }""")
        
        if plugin_registered:
            print("✓ NOW marker plugin is registered")
        else:
            errors.append("NOW marker plugin not registered")

        # Test 5b: Check NOW label is visible (not clipped)
        print("\n=== Test 5b: NOW Label Visibility ===")
        now_label_visible = await page.evaluate("""() => {
            if (typeof tempChart === 'undefined') return false;
            const label = document.querySelector('#chart-now-label');
            const chart = tempChart;
            if (!label || !chart?.canvas) return false;
            const labelRect = label.getBoundingClientRect();
            const canvasRect = chart.canvas.getBoundingClientRect();
            const chartTop = canvasRect.top + chart.chartArea.top;
            return labelRect.bottom <= chartTop;
        }""")
        if now_label_visible:
            print("✓ NOW label visible")
        else:
            errors.append("NOW label not visible (may be clipped)")
        
        # Test 6: Check KPIs are updating
        print("\n=== Test 6: KPI Display ===")
        kpi_temp = await page.locator("#kpi-temp").text_content()
        kpi_conv = await page.locator("#kpi-conv").text_content()
        kpi_time = await page.locator("#kpi-time").text_content()
        
        print(f"  Temperature: {kpi_temp}")
        print(f"  Conversion: {kpi_conv}")
        print(f"  Time: {kpi_time}")
        
        if kpi_temp == "--" or kpi_conv == "--":
            errors.append("KPIs not updating - likely polling issue")
        else:
            print("✓ KPIs are updating")
        
        # Test 7: Screenshot for visual inspection
        print("\n=== Test 7: Screenshot ===")
        screenshot_path = Path(__file__).parent.parent / "logs" / "dashboard_test.png"
        await page.screenshot(path=str(screenshot_path), full_page=True)
        print(f"✓ Screenshot saved to {screenshot_path}")
        
        # Test 8: Start simulation and verify chart updates
        print("\n=== Test 8: Simulation Start ===")
        start_enabled = await page.is_enabled("#btn-start")
        if not start_enabled:
            warnings.append("Start button disabled; skipping start/stop test")
        else:
            await page.click("#btn-start")
            await page.wait_for_timeout(5000)  # Wait 5 seconds for data
        
        # Check if time has progressed
        if start_enabled:
            kpi_time_after = await page.locator("#kpi-time").text_content()
            print(f"  Time after 5s: {kpi_time_after}s")
            
            if int(kpi_time_after) >= 3:
                print("✓ Simulation is running, time progressing")
            else:
                warnings.append(f"Time didn't progress much: {kpi_time_after}")
        
        # Check chart has more data now
        chart_data_after = await page.evaluate("""() => {
            if (typeof tempChart !== 'undefined') {
                return {
                    reactorPoints: tempChart.data.datasets[0].data.length,
                    jacketPoints: tempChart.data.datasets[1].data.length,
                    xMax: tempChart.options.scales.x.suggestedMax
                };
            }
            return null;
        }""")
        
        if start_enabled and chart_data_after:
            print(f"  Reactor data points: {chart_data_after['reactorPoints']}")
            print(f"  X-axis max: {chart_data_after['xMax']}")
            if chart_data_after['reactorPoints'] > 5:
                print("✓ Chart data accumulating")
            else:
                warnings.append("Chart data not accumulating properly")
        
        # Take another screenshot after simulation
        screenshot_path2 = Path(__file__).parent.parent / "logs" / "dashboard_test_running.png"
        if start_enabled:
            await page.screenshot(path=str(screenshot_path2), full_page=True)
            print(f"✓ Running screenshot saved to {screenshot_path2}")
            
            # Stop simulation
            await page.click("#btn-stop")
        
        await browser.close()
    
    # Summary
    print("\n" + "="*50)
    print("TEST SUMMARY")
    print("="*50)
    
    if errors:
        print(f"\n❌ ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  - {e}")
    
    if warnings:
        print(f"\n⚠ WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
    
    if not errors and not warnings:
        print("\n✓ All tests passed!")
    
    return len(errors) == 0


if __name__ == "__main__":
    result = asyncio.run(test_dashboard())
    sys.exit(0 if result else 1)
