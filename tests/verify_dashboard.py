#!/usr/bin/env python3
"""Dashboard verification script - takes screenshot and analyzes state."""

from playwright.sync_api import sync_playwright
import time
import sys

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.goto('http://localhost:8000/')
        time.sleep(1.5)
        
        # Check everything is working
        checks = page.evaluate('''() => {
            const results = {};
            
            // Check chart exists
            const chart = document.querySelector("#chart-temp");
            results.chartExists = !!chart;
            
            // Check feed pipes
            const component_aPipe = document.querySelector("#component_a-pipe");
            const component_bPipe = document.querySelector("#component_b-pipe");
            const solventPipe = document.querySelector("#solvent-pipe");
            results.component_aPipeD = component_aPipe ? component_aPipe.getAttribute("d") : null;
            results.component_bPipeD = component_bPipe ? component_bPipe.getAttribute("d") : null;
            results.solventPipeD = solventPipe ? solventPipe.getAttribute("d") : null;
            
            // Check labels are visible (y > 0)
            const labels = document.querySelectorAll("svg text");
            const feedLabels = Array.from(labels).filter(t => ["COMPONENT_A","COMPONENT_B","SOLVENT"].includes(t.textContent));
            results.labelsY = feedLabels.map(l => ({text: l.textContent, y: parseInt(l.getAttribute("y"))}));
            results.allLabelsVisible = feedLabels.every(l => parseInt(l.getAttribute("y")) > 0);
            
            // Check reactor assembly
            const reactor = document.querySelector("#reactor-assembly");
            results.reactorTransform = reactor ? reactor.getAttribute("transform") : null;
            
            // Check flowing elements
            const flowingPipes = document.querySelectorAll(".flowing");
            results.flowingCount = flowingPipes.length;
            
            // Check connection text  
            const statusBadge = document.querySelector(".connection-badge");
            results.statusText = statusBadge ? statusBadge.textContent.trim() : null;
            
            return results;
        }''')
        
        print('=== DASHBOARD VERIFICATION ===')
        print(f"Chart exists: {checks['chartExists']}")
        print(f"Labels visible: {checks['allLabelsVisible']} - {checks['labelsY']}")
        print(f"Flowing pipes count: {checks['flowingCount']}")
        print(f"Reactor transform: {checks['reactorTransform']}")
        print(f"Status: {checks['statusText']}")
        print()
        print('Pipe paths:')
        print(f"  Component A: {checks['component_aPipeD']}")
        print(f"  Component B: {checks['component_bPipeD']}")
        print(f"  Solvent: {checks['solventPipeD']}")
        
        page.screenshot(path='logs/iteration3.png', full_page=False)
        print()
        print('Screenshot saved: logs/iteration3.png')
        
        # Summary
        issues = []
        if not checks['chartExists']:
            issues.append("Chart not found")
        if not checks['allLabelsVisible']:
            issues.append("Labels clipped (y <= 0)")
        if checks['flowingCount'] > 0:
            issues.append(f"Pipes flowing when idle ({checks['flowingCount']})")
        
        # Verify pipe endpoints connect to reactor
        # Reactor inner vessel top = 120 (local) + 30 (transform) = 150
        # Pipes should end at or below 150 to overlap with reactor
        for pipe_key in ['component_aPipeD', 'component_bPipeD', 'solventPipeD']:
            d = checks[pipe_key]
            if d:
                # Parse last Y coordinate from path
                parts = d.split()
                last_y = int(parts[-1])
                if last_y < 150:
                    issues.append(f"{pipe_key} ends at y={last_y}, doesn't reach reactor top at y=150")
        
        print()
        if issues:
            print(f"ISSUES FOUND: {issues}")
            sys.exit(1)
        else:
            print("ALL CHECKS PASSED ✓")
        
        browser.close()

if __name__ == '__main__':
    main()
