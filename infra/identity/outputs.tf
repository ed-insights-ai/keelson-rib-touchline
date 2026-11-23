output "operator_user_name" {
  value = aws_iam_user.operator.name
}

output "apply_role_arn" {
  value = aws_iam_role.apply.arn
}
