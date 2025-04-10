#! python3
import os
import time
import re
from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader("."))

if __name__ == "__main__":
    for filename in os.listdir("images/obrazy"):
        if "|" in filename:
            new_name = filename.replace("|", "_")
            os.rename(f"images/obrazy/{filename}", f"images/obrazy/{new_name}")
    for filename in os.listdir("src"):
        template = env.get_template(f"src/{filename}")

        with open(f"{filename}", "w+") as f:
            if filename == "galerie.html":
                html = template.render(
                    images=reversed(
                        [
                            f"images/galerie/{name}"
                            for name in sorted(os.listdir("images/galerie/"), key=lambda x: float(x.split("_")[0]), reverse=True)
                            if ".jpg" in name.lower() or ".png" in name.lower()

                        ]
                    )
                )

            elif filename == "obrazy.html":
                html = template.render(
                    images=reversed(
                        [
                            f"images/obrazy/{name}"
                            for name in sorted(os.listdir("images/obrazy/"), key=lambda x: int(re.split(r"[|_]", x)[0]),
                                               )
                            if ".jpg" in name or ".png" in name
                        ]
                    )
                )

            else:
                html = template.render()
            f.write(html)
