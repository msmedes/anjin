def generate_html_output(results: list, output_file: str):
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Dependency Updates</title>
        <style>
            body { font-family: Arial, sans-serif; margin: 0; padding: 20px; }
            h1 { color: #333; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            tr:nth-child(even) { background-color: #f9f9f9; }
            .status-SUCCESS { color: green; }
            .status-FAILURE, .status-NOT_FOUND { color: red; }
        </style>
    </head>
    <body>
        <h1>Dependency Updates</h1>
        <table>
            <tr>
                <th>Package</th>
                <th>Current Version</th>
                <th>Latest Version</th>
                <th>Status</th>
                <th>Summary</th>
            </tr>
    """

    for result in results:
        if result:
            package, current_version, latest_version, changelog_result = result
            html_content += f"""
            <tr>
                <td>{package}</td>
                <td>{current_version}</td>
                <td>{latest_version}</td>
                <td class="status-{changelog_result.status.value}">{changelog_result.status.value}</td>
                <td>{changelog_result.summary or 'N/A'}</td>
            </tr>
            """

    html_content += """
        </table>
    </body>
    </html>
    """

    with open(output_file, "w") as f:
        f.write(html_content)
