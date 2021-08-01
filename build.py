#! python3
import jinja2, os, shutil

from jinja2 import Environment, FileSystemLoader

env = Environment(loader=FileSystemLoader('.'))

if __name__ == "__main__":
    try:
        shutil.rmtree("./_site")
    except FileNotFoundError:
        print("_site not found")

    os.mkdir("./_site")
    shutil.copytree("assets", "./_site/assets")
    shutil.copytree("images", "./_site/images")

    for filename in os.listdir("src"):
        template = env.get_template(f"src/{filename}")

        with open(f"_site/{filename}", "w+") as f:
            if filename == "galerie.html":
                html = template.render(
                    images = [f"images/galerie/{name}" for name in os.listdir("images/galerie/") 
                        if ".jpg" in name or ".png" in name]
                )
                print(os.listdir("images/galerie/"))

            else:
                html = template.render()
            f.write(html)


