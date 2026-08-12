"""Model layer: segmentation, forecasting and review sentiment.

Every module reads from the dbt mart layer and writes a versioned result table
back into the `ml` schema, so model outputs are queryable alongside the facts
and the dashboard never has to run a model at request time.
"""
