#! python3
import jinja2, os, shutil

from jinja2 import Environment, FileSystemLoader
import time

env = Environment(loader=FileSystemLoader('.'))

if __name__ == "__main__":
    for filename in os.listdir("src"):
        template = env.get_template(f"src/{filename}")

        with open(f"{filename}", "w+") as f:
            if filename == "galerie.html":
                html = template.render(
                    images=[f"images/galerie/{name}" for name in os.listdir("images/galerie/")
                            if ".jpg" in name or ".png" in name]
                )
                print(f"Compilation time: {time.time()}")

            else:
                html = template.render()
            f.write(html)


