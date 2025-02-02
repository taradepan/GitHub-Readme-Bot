import os
from groq import Groq
import logging
from datetime import datetime
import requests
from base64 import b64decode
import json
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def extract_current_info(log_text: str) -> tuple:
    
    date_pattern = r'Current Date and Time \(UTC - YYYY-MM-DD HH:MM:SS formatted\): (\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'
    date_match = re.search(date_pattern, log_text)
    if date_match:
        formatted_date = date_match.group(1)
    else:
        formatted_date = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')

    login_pattern = r"Current User's Login: (\w+)"
    login_match = re.search(login_pattern, log_text)
    user_login = login_match.group(1) if login_match else "unknown"

    return formatted_date, user_login

def clean_output(generated_content: str) -> str:
    cleaned = re.sub(r'<think>.*?</think>', '', generated_content, flags=re.DOTALL)
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    cleaned = cleaned.strip()
    
    return cleaned

def get_repo_data(repo_url: str) -> tuple:
    """
    Get repository data using GitHub API
    """
    try:
        _, _, _, owner, repo = repo_url.rstrip('/').split('/')
        api_base = "https://api.github.com"
        headers = {
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {os.getenv('GITHUB_TOKEN')}"
        }
        
        logger.info(f"Fetching repository data for {owner}/{repo}")
        
        repo_response = requests.get(
            f"{api_base}/repos/{owner}/{repo}",
            headers=headers
        )
        
        if repo_response.status_code != 200:
            logger.error(f"Failed to fetch repo data: {repo_response.text}")
            raise Exception(f"GitHub API returned {repo_response.status_code}: {repo_response.text}")
            
        repo_data = repo_response.json()
        logger.info(f"Successfully fetched repository info for {owner}/{repo}")
        
        summary = f"""
            Repository Information:
            - Name: {repo_data.get('name')}
            - Description: {repo_data.get('description', 'No description provided')}
            - Primary Language: {repo_data.get('language', 'Not specified')}
            - Topics: {', '.join(repo_data.get('topics', ['None specified']))}
            - Stars: {repo_data.get('stargazers_count', 0)}
            - Forks: {repo_data.get('forks_count', 0)}
            - Created: {repo_data.get('created_at', 'Unknown')}
            - Last Updated: {repo_data.get('updated_at', 'Unknown')}
            """

        default_branch = repo_data.get('default_branch', 'main')
        logger.info(f"Default branch is {default_branch}")

        tree_response = requests.get(
            f"{api_base}/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1",
            headers=headers
        )
        
        if tree_response.status_code != 200:
            logger.error(f"Failed to fetch tree data: {tree_response.text}")
            raise Exception(f"GitHub API returned {tree_response.status_code}: {tree_response.text}")
            
        tree_data = tree_response.json()
        logger.info(f"Successfully fetched repository tree")

        tree = "File Structure:\n"
        content = "Code Analysis:\n"
        
        binary_extensions = {
            '.png', '.jpg', '.jpeg', '.gif', '.ico', '.pdf', '.zip', '.tar', '.gz',
            '.rar', '.7z', '.exe', '.dll', '.so', '.dylib', '.class', '.pyc',
            '.pyo', '.pyd', '.db', '.sqlite', '.sqlite3', '.bin', '.dat', '.iso'
        }
        
        excluded_paths = {
            '.git/', '.github/workflows/', 'node_modules/', 'venv/', 'env/',
            '__pycache__/', 'dist/', 'build/', 'coverage/', '.pytest_cache/'
        }
        
        for item in tree_data.get('tree', []):
            path = item.get('path', '')
            if not path:
                continue
                
            tree += f"- {path}\n"
            
            if (item.get('type') == 'blob' and
                not any(path.endswith(ext) for ext in binary_extensions) and
                not any(excl in path for excl in excluded_paths)):
                try:
                    file_response = requests.get(
                        f"{api_base}/repos/{owner}/{repo}/contents/{path}",
                        headers=headers
                    )
                    
                    if file_response.status_code == 200:
                        file_data = file_response.json()
                        if file_data.get('content'):
                            try:
                                file_content = b64decode(file_data['content']).decode('utf-8')
                                if file_content.strip():  # Skip empty files
                                    content += f"\n### {path}\n```\n{file_content[:1000]}...\n```\n"
                                    logger.info(f"Processed file: {path}")
                            except UnicodeDecodeError:
                                logger.info(f"Skipping binary file: {path}")
                                continue
                except Exception as e:
                    logger.error(f"Error fetching content for {path}: {str(e)}")
                    continue

        logger.info(f"Successfully processed {len(tree_data.get('tree', []))} files")
        return summary, tree, content

    except Exception as e:
        logger.error(f"Error in get_repo_data: {str(e)}")
        raise Exception(f"Failed to analyze repository: {str(e)}")

def analyze_repo_sync(repo_url: str, context: dict = None) -> str:
    try:
        logger.info(f"Starting analysis for {repo_url}")
        
        summary, tree, content = get_repo_data(repo_url)
        
        log_text = f"Current Date and Time (UTC - YYYY-MM-DD HH:MM:SS formatted): 2025-02-02 10:45:04\nCurrent User's Login: taradepan"
        current_date, user_login = extract_current_info(log_text)
        
        client = Groq(
            api_key=os.environ.get("GROQ_API_KEY"),
        )

        analysis_prompt = f"""Imagine you are a Senior Developer, expert in writing Readme.md. Analyze this GitHub repository and create a comprehensive README.

Repository URL: {repo_url}

Repository Overview:
{summary}

File Structure:
{tree}

Code Analysis:
{content}

Generate a detailed README in markdown format that includes:
1. Project Title and Description
2. Key Features and Capabilities
3. Technologies and Dependencies Used (no need to mention all, just the key ones) 
4. Setup Instructions
5. Usage Guide
6. Contribution Guidelines
7. Add emojis to make it more engaging
8. Also refer the previous readme for more information (IF EXISTS)
9. Also mention IF there are any additional notes or tips for the users
10. Don't give any false information

Important Notes:
- Keep it clean and professional
- Make sure you understand the project well
- Focus on technical accuracy
- Don't mention anything about previous readme, your output will be the only readme
- Don't add any metadata sections
- Don't add repository stats
- Use clear and concise language
- Don't mention anything you are not sure about
- Your output will be directly used as the README.md file so make sure it's perfect!
Remember: ONLY GENERATE THE FINAL README FILE IN MARKDOWN FORMAT"""

        chat_completion = client.chat.completions.create(
            messages=[{
                "role": "user",
                "content": analysis_prompt
            }],
            model="llama-3.3-70b-versatile",
            temperature=0.2,
            max_tokens=4000
        )

        generated_content = chat_completion.choices[0].message.content
        generated_content += f"\n\n---\n*Generated by GH-Readme-Bot on {current_date} UTC*"
        return clean_output(generated_content)

    except Exception as e:
        logger.error(f"Analysis error: {str(e)}")
        return f"""
# Repository Analysis Error

An error occurred while analyzing the repository:
`{str(e)}`

Please check:
1. Repository access permissions
2. API key configuration
3. Network connectivity

---
*Generated by GH-Readme-Bot on {current_date} UTC*"""

async def analyze_repo(repo_url: str, context: dict = None) -> str:
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, analyze_repo_sync, repo_url, context)

if __name__ == "__main__":
    import asyncio
    repo_url = "https://github.com/username/repo"
    result = asyncio.run(analyze_repo(repo_url))
    print(result)