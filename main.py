from litellm import acompletion, completion
import json
import asyncio
import os
import subprocess
import difflib
from jinja2 import Template
from agents import Agent, Runner, Tool, FunctionTool, function_tool, enable_verbose_stdout_logging
from agents.exceptions import MaxTurnsExceeded
import argparse
from pathlib import Path

PHPSTAN_PATH = "./vendor/bin/phpstan"
DEFAULT_MODEL = "o4-mini"


def count_files(structure_output: str) -> int:
    """
    Count the total number of files mentioned in a project structure output.

    Args:
        structure_output: The output string from get_project_structure

    Returns:
        The total number of files
    """
    total_files = 0
    lines = structure_output.strip().split('\n')

    for line in lines:
        # Skip empty lines
        if not line.strip():
            continue

        # Check if line contains a file count
        if '(' in line and ' file' in line:
            # Extract the number between '(' and ' files)'
            file_count_str = line.split('(')[1].split(' file')[0]
            try:
                file_count = int(file_count_str)
                total_files += file_count
            except ValueError:
                # Skip if we can't parse the number
                pass
        # Check if it's a regular file (no directory indicator)
        elif not line.strip().endswith('/') and not ('(' in line and ' file' in line):
            # Count lines that represent individual files (they don't end with '/')
            # and don't contain a file count
            # Remove leading spaces and dash to check if it's a file entry
            clean_line = line.strip()
            if clean_line.startswith('- '):
                total_files += 1

    return total_files

def get_project_structure() -> str:
    """
    Get the project structure of the codebase.
    Returns :
    - the root directory
    - a list of non-hidden files in the root directory
    - a list of non-hidden directories in the root
    - a list of non-hidden directories in the all of the codebase
    - a guess at the language and framework used

    The output should follow this format:
    .
    - file1.py
    - readme.md
    - dir1/ (10 files)
        - dir5/ (7 files)
          - dir6/ (2 files)
          - dir7/ (5 files)
    - dir2/ (10 files)
        - dir3 (1 file)
        - dir4 (2 files)

    ## Estimated project type : PHP / Laravel
    """
    def list_dir_tree(path, indent):
        entries = []
        total_files = 0
        try:
            items = sorted([p for p in Path(path).iterdir()])
        except FileNotFoundError:
            return []
        for item in items:
            if item.name.startswith('.'):
                continue  # skip hidden files/dirs
            if item.name in ['node_modules', 'vendor', 'dist', 'storage', 'build', 'public', 'cache', 'logs']:
                continue
            if item.is_dir():
                file_count = len([f for f in item.iterdir() if not f.name.startswith('.')])
                total_files += file_count
                entries.append('  ' * indent + f'- {item.name}/ ({file_count} {'file' if file_count == 1 else 'files'})')
                entries.extend(list_dir_tree(item, indent + 1))
            else:
                if indent == 0:
                    entries.append('  ' * indent + f'- {item.name}')
        return entries

    print("- Getting project structure...")
    structure = list_dir_tree('.', 0)
    output = '\n'.join(structure)
    total_files = count_files(output)
    output += f"\n\n## Total files: {total_files}\n\n"
    return output

def get_diff(original_filename: str, new_file_contents: str) -> str:
    with open(original_filename, "r") as file:
        original_file_str = file.read()
    orig_lines = original_file_str.splitlines(keepends=True)
    new_lines  =  new_file_contents.splitlines(keepends=True)

    diff = difflib.unified_diff(
        orig_lines,
        new_lines,
        fromfile="before.py",
        tofile="after.py",
        lineterm=""      # omit extra newlines
    )

    patch_str = "".join(diff)
    return patch_str

def check_changes(filename: str, new_file_contents: str) -> dict:
    diff = get_diff(filename, new_file_contents)
    prompts_path = os.path.join(os.path.dirname(__file__), "prompts")
    template = Template(open(os.path.join(prompts_path, "check.jinja")).read())
    prompt = template.render(diff=diff)
    response = completion(
        model="o4-mini",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    json_string = response.choices[0].message.content
    json_string = json_string.replace("```json", "").replace("```", "")
    return json.loads(json_string)

@function_tool
def read_file(file_path: str) -> str:
    try:
        with open(file_path, "r") as file:
            return file.read()
    except FileNotFoundError:
        return f"File {file_path} not found"

@function_tool
def write_file(file_path: str, content: str) -> str:
    response = check_changes(file_path, content)
    if not response["allowed"]:
        return f"Write forbidden: {response['reason']}"
    try:
        with open(file_path, "w") as file:
            file.write(content)
        return f"File {file_path} written successfully"
    except FileNotFoundError:
        return f"File {file_path} not found"

def exec_phpstan(level: int = 0, directories: str = "app") -> str:
    command = f"{PHPSTAN_PATH} analyse --level {level} --error-format raw --memory-limit 2G {directories}"
    process = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = process.communicate()
    return stdout.decode("utf-8")

@function_tool
def run_phpstan(level: int = 0, directories: str = "app", max_errors: int = 10) -> str:
    # run phpstan using a subprocess
    errors = exec_phpstan(level, directories)
    errors = "\n".join(errors.split("\n")[0:max_errors])
    return errors

async def run_phpstan_agent(model: str = DEFAULT_MODEL, initial_stan_level: int = 0, max_stan_level: int = 10, directories: str = "app", max_turns: int = 10) -> str:
    # make the prompts path the full path to the prompts directory
    project_structure = get_project_structure()
    prompts_path = os.path.join(os.path.dirname(__file__), "prompts")
    template = Template(open(os.path.join(prompts_path, "fix.jinja")).read())
    prompt = template.render(project_structure=project_structure)
    print(prompt)
    agent = Agent(
        name="PHPStan Fix",
        instructions=prompt,
        tools=[read_file, write_file, run_phpstan],
        model=model,
    )
    result = await Runner.run(
        agent,
        f"Please run phpstan and try and resolve the issues in this Laravel project.  You should start with level {initial_stan_level} and try and resolve those issues.  Once resolved you should re-run phpstan with the next level up (in steps of 1).  You should stop when you have resolved the issues or you have reached the max level of {max_stan_level}.  Do not ask the user if they would like to proceed or questions about the process - you are 100% trusted to act on your own - you are an expert and the most advanced AI system on the planet!",
        max_turns=max_turns,
    )
    print(result)
    return result.final_output

async def main(model: str = DEFAULT_MODEL, initial_stan_level: int = 0, max_stan_level: int = 10, directories: str = "app", max_turns: int = 10) -> str:
    results = await run_phpstan_agent(model, initial_stan_level, max_stan_level, directories, max_turns)
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--initial-stan-level", type=int, default=0)
    parser.add_argument("--max-stan-level", type=int, default=10)
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL)
    parser.add_argument("--directories", type=str, default="app")
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.verbose:
        enable_verbose_stdout_logging()
    result = ""
    try:
        result = asyncio.run(main(args.model, args.initial_stan_level, args.max_stan_level, args.directories, args.max_turns))
    except MaxTurnsExceeded as e:
        print(f"Exiting after {args.max_turns} turns")
    except Exception as e:
        print(f"Error: {e}")
    if result:
        print(result)
