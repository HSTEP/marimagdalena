#! python3
import jinja2, os, shutil

from jinja2 import Environment, FileSystemLoader
import time

env = Environment(loader=FileSystemLoader("."))

if __name__ == "__main__":
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
                            for name in sorted(os.listdir("images/obrazy/"), key=lambda x: int(x.split("|")[0]),
                                               )
                            if ".jpg" in name or ".png" in name
                        ]
                    )
                )

            else:
                html = template.render()
            f.write(html)
