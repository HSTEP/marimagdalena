from PIL import Image

def crop_to_square(image_path, out):
    # Open the image
    image = Image.open(image_path)

    # Get the width and height of the image
    width, height = image.size

    # Calculate the coordinates of the square
    if width > height:
        left = (width - height) / 2
        top = 0
        right = left + height
        bottom = height
    else:
        left = 0
        top = (height - width) / 2
        right = width
        bottom = top + width

    # Crop the image to the square
    cropped_image = image.crop((left, top, right, bottom))

    # Save the cropped image
    print(out + "/centered_" + image_path.split("/")[-1])
    cropped_image.save(out + "/centered_" + image_path.split("/")[-1])


import os

images = os.listdir("images/galerie_backup")

[crop_to_square("images/galerie_backup/" + image, "images/galerie/") for image in images]