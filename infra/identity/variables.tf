variable "region" {
  description = "AWS region of the Touchline resources."
  type        = string
  default     = "us-east-1"
}

variable "operator_user_name" {
  description = "IAM user for day-to-day Touchline work."
  type        = string
  default     = "touchline-operator"
}

variable "apply_role_name" {
  description = "Role the operator steps up to for infra/bootstrap applies."
  type        = string
  default     = "touchline-bootstrap-apply"
}
