Put the real CSV files you downloaded from Kaggle here, then run from the project folder:

  python train.py sentiment data/Reviews.csv
  python train.py price data/products.csv

Restart `python app.py` afterwards. Admin -> "Model Lab" will show the real-data accuracy, F1, confusion matrix and model comparison.

Review dataset ideas (search on Kaggle): "Amazon Fine Food Reviews", "Flipkart product reviews". You need a review text column plus a rating/label column.
Price dataset ideas: "Amazon Products Sales Dataset", "Flipkart products". You need selling price, MRP, rating, number of ratings and category.
If your column names differ:  python train.py sentiment file.csv --text COLUMN --label COLUMN
