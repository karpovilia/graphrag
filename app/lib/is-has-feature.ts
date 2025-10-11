import features from "../features.json";

export function isHasFeature(feature: keyof typeof features) {
  return features[feature];
}
