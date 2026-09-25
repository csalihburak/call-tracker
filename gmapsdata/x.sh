#!/bin/bash
touch dalga2-sonuc.csv && docker run -d \
  -v $PWD/dalga2-buyuksehir.txt:/input.txt \
  -v $PWD/dalga2-sonuc.csv:/results.csv \
  gosom/google-maps-scraper \
  -depth 10 \
  -input /input.txt \
  -results /results.csv \
  -lang tr \
  -exit-on-inactivity 3m \
  -email

touch dalga3-sonuc.csv && docker run -d \
  -v $PWD/dalga3-anadolu.txt:/input.txt \
  -v $PWD/dalga3-sonuc.csv:/results.csv \
  gosom/google-maps-scraper \
  -depth 10 \
  -input /input.txt \
  -results /results.csv \
  -lang tr \
  -exit-on-inactivity 3m \
  -email

touch dalga4-sonuc.csv && docker run -d \
  -v $PWD/dalga4-istanbul.txt:/input.txt \
  -v $PWD/dalga4-sonuc.csv:/results.csv \
  gosom/google-maps-scraper \
  -depth 10 \
  -input /input.txt \
  -results /results.csv \
  -lang tr \
  -exit-on-inactivity 3m \
  -email