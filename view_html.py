#!/usr/bin/env python3
"""
Script per generare una visualizzazione HTML interattiva di un file JSON ad albero.
"""

import argparse
import json
import html
from pathlib import Path


def generate_html(json_data: dict, title: str = "JSON Tree Viewer") -> str:
    """Genera HTML con visualizzazione ad albero del JSON."""

    json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
    json_escaped = html.escape(json_str)

    html_template = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{html.escape(title)}</title>
    <style>
        :root {{
            --bg-primary: #1e1e1e;
            --bg-secondary: #252526;
            --bg-hover: #2a2d2e;
            --text-primary: #d4d4d4;
            --text-secondary: #858585;
            --accent: #007acc;
            --key-color: #9cdcfe;
            --string-color: #ce9178;
            --number-color: #b5cea8;
            --boolean-color: #569cd6;
            --null-color: #569cd6;
            --border-color: #454545;
        }}

        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}

        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }}

        header {{
            background: var(--bg-secondary);
            padding: 1rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 1rem;
        }}

        h1 {{
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--text-primary);
        }}

        .controls {{
            display: flex;
            gap: 0.5rem;
            flex-wrap: wrap;
        }}

        button {{
            background: var(--accent);
            color: white;
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.875rem;
            transition: opacity 0.2s;
        }}

        button:hover {{
            opacity: 0.9;
        }}

        button.secondary {{
            background: var(--bg-hover);
            color: var(--text-primary);
            border: 1px solid var(--border-color);
        }}

        input[type="text"] {{
            background: var(--bg-primary);
            border: 1px solid var(--border-color);
            color: var(--text-primary);
            padding: 0.5rem;
            border-radius: 4px;
            font-size: 0.875rem;
            width: 200px;
        }}

        main {{
            flex: 1;
            overflow: auto;
            padding: 1rem;
        }}

        .tree-container {{
            font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
            font-size: 0.875rem;
            line-height: 1.5;
        }}

        .tree-node {{
            margin-left: 1.5rem;
            border-left: 1px solid var(--border-color);
            padding-left: 0.5rem;
        }}

        .tree-node.collapsed > .tree-children {{
            display: none;
        }}

        .tree-node.collapsed .toggle::before {{
            content: "▶";
        }}

        .tree-header {{
            display: flex;
            align-items: center;
            cursor: pointer;
            padding: 0.125rem 0;
            border-radius: 3px;
        }}

        .tree-header:hover {{
            background: var(--bg-hover);
        }}

        .toggle {{
            width: 1rem;
            height: 1rem;
            display: flex;
            align-items: center;
            justify-content: center;
            margin-right: 0.25rem;
            color: var(--text-secondary);
            font-size: 0.75rem;
        }}

        .toggle::before {{
            content: "▼";
        }}

        .toggle.leaf::before {{
            content: "";
        }}

        .key {{
            color: var(--key-color);
            margin-right: 0.5rem;
        }}

        .separator {{
            color: var(--text-secondary);
            margin: 0 0.25rem;
        }}

        .value {{
            display: inline;
        }}

        .value.string {{
            color: var(--string-color);
        }}

        .value.number {{
            color: var(--number-color);
        }}

        .value.boolean {{
            color: var(--boolean-color);
        }}

        .value.null {{
            color: var(--null-color);
        }}

        .bracket {{
            color: var(--text-secondary);
        }}

        .count {{
            color: var(--text-secondary);
            font-size: 0.75rem;
            margin-left: 0.5rem;
        }}

        .matched {{
            background: rgba(255, 215, 0, 0.3);
            border-radius: 2px;
        }}

        .hidden {{
            display: none !important;
        }}

        .preview {{
            color: var(--text-secondary);
            font-style: italic;
            margin-left: 0.5rem;
        }}

        .root {{
            margin-left: 0;
            border-left: none;
            padding-left: 0;
        }}
    </style>
</head>
<body>
    <header>
        <h1>📁 {html.escape(title)}</h1>
        <div class="controls">
            <input type="text" id="search" placeholder="Search keys/values...">
            <button onclick="expandAll()">Expand All</button>
            <button onclick="collapseAll()">Collapse All</button>
            <button class="secondary" onclick="toggleSource()">View Source</button>
        </div>
    </header>
    <main>
        <div id="tree" class="tree-container"></div>
        <pre id="source" class="hidden" style="background: var(--bg-secondary); padding: 1rem; border-radius: 4px; overflow: auto;"><code>{json_escaped}</code></pre>
    </main>

    <script>
        const jsonData = {json_str};

        function renderValue(value) {{
            if (value === null) return '<span class="value null">null</span>';
            if (typeof value === 'boolean') return `<span class="value boolean">${{value}}</span>`;
            if (typeof value === 'number') return `<span class="value number">${{value}}</span>`;
            if (typeof value === 'string') return `<span class="value string">"${{escapeHtml(value)}}"</span>`;
            return '';
        }}

        function escapeHtml(text) {{
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }}

        function renderNode(key, value, isRoot = false) {{
            const node = document.createElement('div');
            node.className = 'tree-node' + (isRoot ? ' root' : '');

            const header = document.createElement('div');
            header.className = 'tree-header';

            const toggle = document.createElement('span');
            toggle.className = 'toggle';

            const isObject = value !== null && typeof value === 'object';
            const isArray = Array.isArray(value);
            const keys = isObject ? Object.keys(value) : [];
            const hasChildren = keys.length > 0;

            if (!hasChildren) {{
                toggle.classList.add('leaf');
            }}

            let keyHtml = '';
            if (key !== null) {{
                const displayKey = isArray ? key : `"${{key}}"`;
                keyHtml = `<span class="key">${{displayKey}}</span>`;
            }}

            let valueHtml = '';
            let bracketOpen = '';
            let bracketClose = '';
            let countBadge = '';

            if (isObject) {{
                if (isArray) {{
                    bracketOpen = '<span class="bracket">[</span>';
                    bracketClose = '<span class="bracket">]</span>';
                }} else {{
                    bracketOpen = '<span class="bracket">{{</span>';
                    bracketClose = '<span class="bracket">}}</span>';
                }}
                countBadge = `<span class="count">${{keys.length}} items</span>`;
            }} else {{
                valueHtml = renderValue(value);
            }}

            header.innerHTML = `${{toggle.outerHTML}}${{keyHtml}}${{key !== null ? '<span class="separator">:</span>' : ''}}${{bracketOpen}}${{countBadge}}${{bracketClose}}${{valueHtml}}`;
            node.appendChild(header);

            if (hasChildren) {{
                const children = document.createElement('div');
                children.className = 'tree-children';

                keys.forEach((childKey, index) => {{
                    const childNode = renderNode(childKey, value[childKey]);
                    children.appendChild(childNode);
                }});

                node.appendChild(children);

                header.querySelector('.toggle').addEventListener('click', (e) => {{
                    e.stopPropagation();
                    node.classList.toggle('collapsed');
                }});

                header.addEventListener('click', () => {{
                    node.classList.toggle('collapsed');
                }});
            }}

            return node;
        }}

        function renderTree() {{
            const container = document.getElementById('tree');
            container.innerHTML = '';
            const root = renderNode(null, jsonData, true);
            container.appendChild(root);
        }}

        function expandAll() {{
            document.querySelectorAll('.tree-node.collapsed').forEach(node => {{
                node.classList.remove('collapsed');
            }});
        }}

        function collapseAll() {{
            document.querySelectorAll('.tree-node:not(.root):not(:has(.tree-children:empty))').forEach(node => {{
                const hasRealChildren = node.querySelector('.tree-children')?.children.length > 0;
                if (hasRealChildren) {{
                    node.classList.add('collapsed');
                }}
            }});
        }}

        function toggleSource() {{
            const tree = document.getElementById('tree');
            const source = document.getElementById('source');
            tree.classList.toggle('hidden');
            source.classList.toggle('hidden');
        }}

        function search(query) {{
            if (!query) {{
                document.querySelectorAll('.matched').forEach(el => el.classList.remove('matched'));
                document.querySelectorAll('.hidden').forEach(el => {{
                    if (!el.id || (el.id !== 'source')) {{
                        el.classList.remove('hidden');
                    }}
                }});
                return;
            }}

            const lowerQuery = query.toLowerCase();
            const allNodes = document.querySelectorAll('.tree-node');

            allNodes.forEach(node => {{
                node.classList.add('hidden');
            }});

            const matchedHeaders = [];
            document.querySelectorAll('.tree-header').forEach(header => {{
                const text = header.textContent.toLowerCase();
                if (text.includes(lowerQuery)) {{
                    header.classList.add('matched');
                    matchedHeaders.push(header);
                }} else {{
                    header.classList.remove('matched');
                }}
            }});

            matchedHeaders.forEach(header => {{
                let node = header.closest('.tree-node');
                while (node) {{
                    node.classList.remove('hidden');
                    node.classList.remove('collapsed');
                    node = node.parentElement?.closest('.tree-node');
                }}
            }});
        }}

        document.getElementById('search').addEventListener('input', (e) => {{
            search(e.target.value);
        }});

        renderTree();
    </script>
</body>
</html>'''

    return html_template


def main():
    parser = argparse.ArgumentParser(
        description="Generate interactive HTML tree viewer from JSON file"
    )
    parser.add_argument("json_file", help="Path to JSON file")
    parser.add_argument("output_html", nargs="?", help="Output HTML file path")
    args = parser.parse_args()

    json_path = Path(args.json_file)
    if not json_path.exists():
        print(f"Error: File not found: {json_path}")
        return 1

    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON - {e}")
        return 1

    if args.output_html:
        output_path = Path(args.output_html)
    else:
        output_path = json_path.with_suffix(".html")

    title = json_path.stem
    html_content = generate_html(data, title)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"Generated: {output_path}")
    return 0


if __name__ == "__main__":
    exit(main())
