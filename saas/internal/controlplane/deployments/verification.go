package deployments

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
)

// MakeVerificationRecord renders the DNS TXT challenge per ADR 015.
//
// The token is hex(HMAC-SHA256(deployment_id || ":" || domain, hmacKey)).
// 192 effective bits — comfortably above the 128-bit floor.
//
// hmacKey is the per-Deployment BYOD HMAC key. Phase 11 uses an in-memory
// placeholder (defaultHMACKey()); Phase 12d stores the real key in
// OpenBao KV at secret/data/<dep_id>/byod_hmac_key.
func MakeVerificationRecord(deploymentID, domain string, hmacKey []byte) VerificationRecord {
	h := hmac.New(sha256.New, hmacKey)
	h.Write([]byte(deploymentID))
	h.Write([]byte{':'})
	h.Write([]byte(domain))
	token := hex.EncodeToString(h.Sum(nil))
	return VerificationRecord{
		RecordName:  "_saas-verify." + domain,
		RecordType:  "TXT",
		RecordValue: "saas-verify=" + token,
	}
}

// CompareVerificationValue is a constant-time compare of the expected TXT
// value against the observed TXT value, guarding the verify endpoint
// against timing-oracle attacks (ADR 015).
func CompareVerificationValue(expected, observed string) bool {
	return subtle.ConstantTimeCompare([]byte(expected), []byte(observed)) == 1
}
