import re
import json

def clean_text(raw: str) -> str:
    text = re.sub(r'<[^>]+>', ' ', raw)           
    text = re.sub(r'https?://\S+', ' ', text)     
    text = re.sub(r'[^\w\s]', ' ', text)          
    text = text.lower().strip()
    text = re.sub(r'\s{2,}', ' ', text)
    return text

import spacy
nlp = spacy.load('ru_core_news_sm')  

def tokenize_and_lemmatize(text: str):
    doc = nlp(text)
    return [tok.lemma_ for tok in doc if tok.is_alpha and not tok.is_stop]

from sklearn.feature_extraction.text import TfidfVectorizer
vectorizer = TfidfVectorizer(max_df=0.8, min_df=2, ngram_range=(1,2))

from sklearn.linear_model import LogisticRegression
sentiment_model = LogisticRegression()

from gensim import corpora, models

lda_dictionary = None
lda_model = None

def train_lda(token_lists, num_topics=5):
    global lda_dictionary, lda_model
    lda_dictionary = corpora.Dictionary(token_lists)
    corpus = [lda_dictionary.doc2bow(tokens) for tokens in token_lists]
    lda_model = models.LdaModel(corpus, id2word=lda_dictionary, num_topics=num_topics)

def get_topics(tokens):
    bow = lda_dictionary.doc2bow(tokens)
    return lda_model.get_document_topics(bow)  

from rake_nltk import Rake
rake = Rake(language='russian')

def extract_keywords(text: str, max_phrases=5):
    rake.extract_keywords_from_text(text)
    return rake.get_ranked_phrases()[:max_phrases]

def analyze_feedback(raw_comment: str, feedback_id):
    clean = clean_text(raw_comment)
    tokens = tokenize_and_lemmatize(clean)
    joined = ' '.join(tokens)
    vec = vectorizer.transform([joined])
    sent_score = float(sentiment_model.predict_proba(vec)[0,1])
    topics = get_topics(tokens)  
    keywords = extract_keywords(raw_comment)

    result = {
        'clean_text': joined,
        'sentiment_score': sent_score,
        'topics': topics,
        'keywords': keywords
    }
    
    return result
