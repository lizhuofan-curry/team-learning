# 官方60题批量评估进度

配置：qwen3:4b / schema / qwen-recommended / notes。

已评分6/60，已通过4题，未评分54题。

生成或评分失败单列，无裁判分数不填0；已评分均分不代表60题均分。

仅已评分用例的平均reward：0.5833333333333334。

| 层次 | 计划 | 生成完成 | 生成失败 | 已评分 | 通过 | 已评分均分 |
| --- | --- | --- | --- | --- | --- | --- |
| layer1 | 20 | 5 | 15 | 5 | 4 | 0.7 |
| layer2 | 20 | 1 | 19 | 1 | 0 | 0.0 |
| layer3 | 20 | 0 | 20 | 0 | 0 | None |

| 用例 | 生成 | 裁判 | passed | reward |
| --- | --- | --- | --- | --- |
| layer1_01_bank_account | saved | scored | True | 0.8125 |
| layer1_02_insurance_claim | incomplete | pending | — | — |
| layer1_03_medical_appointment | incomplete | pending | — | — |
| layer1_04_airline_booking | saved | scored | True | 0.9375 |
| layer1_05_internet_service | saved | scored | True | 0.875 |
| layer1_06_credit_card_app | incomplete | pending | — | — |
| layer1_07_car_rental | incomplete | pending | — | — |
| layer1_08_hotel_reservation | incomplete | pending | — | — |
| layer1_09_home_security | saved | scored | False | 0.0 |
| layer1_10_pharmacy_transfer | saved | scored | True | 0.875 |
| layer1_11_mortgage_application | incomplete | pending | — | — |
| layer1_12_gym_membership | incomplete | pending | — | — |
| layer1_13_tax_preparation | incomplete | pending | — | — |
| layer1_14_cellphone_upgrade | incomplete | pending | — | — |
| layer1_15_college_enrollment | incomplete | pending | — | — |
| layer1_16_home_renovation | incomplete | pending | — | — |
| layer1_17_veterinary_care | incomplete | pending | — | — |
| layer1_18_retirement_planning | incomplete | pending | — | — |
| layer1_19_wedding_venue | incomplete | pending | — | — |
| layer1_20_daycare_enrollment | incomplete | pending | — | — |
| layer2_01_multiple_vehicles | incomplete | pending | — | — |
| layer2_02_multiple_properties | incomplete | pending | — | — |
| layer2_03_multiple_credit_cards | incomplete | pending | — | — |
| layer2_04_multiple_subscriptions | incomplete | pending | — | — |
| layer2_05_multiple_bank_accounts | incomplete | pending | — | — |
| layer2_06_multiple_insurance_policies | incomplete | pending | — | — |
| layer2_07_multiple_medications | saved | scored | False | 0.0 |
| layer2_08_multiple_rental_properties | incomplete | pending | — | — |
| layer2_09_multiple_children_schools | incomplete | pending | — | — |
| layer2_10_travel_rebooking_chain | incomplete | pending | — | — |
| layer2_11_medical_treatment_evolution | incomplete | pending | — | — |
| layer2_12_contradictory_financial_instructions | incomplete | pending | — | — |
| layer2_13_home_services_cascade | incomplete | pending | — | — |
| layer2_14_product_order_modifications | incomplete | pending | — | — |
| layer2_15_employment_negotiation | incomplete | pending | — | — |
| layer2_16_family_event_conflicting_input | incomplete | pending | — | — |
| layer2_17_tech_support_cascade | incomplete | pending | — | — |
| layer2_18_education_prerequisite_chain | incomplete | pending | — | — |
| layer2_19_investment_market_response | incomplete | pending | — | — |
| layer2_20_healthcare_coverage_changes | incomplete | pending | — | — |
| layer3_01_travel_coordination | incomplete | pending | — | — |
| layer3_02_medical_insurance_coordination | incomplete | pending | — | — |
| layer3_03_home_purchase_coordination | incomplete | pending | — | — |
| layer3_04_warranty_coordination | incomplete | pending | — | — |
| layer3_05_tax_preparation_synthesis | incomplete | pending | — | — |
| layer3_06_business_expansion_coordination | incomplete | pending | — | — |
| layer3_07_eldercare_coordination | incomplete | pending | — | — |
| layer3_08_divorce_settlement_complexity | incomplete | pending | — | — |
| layer3_09_vehicle_accident_cascade | incomplete | pending | — | — |
| layer3_10_education_financing_maze | incomplete | pending | — | — |
| layer3_11_immigration_status_complexity | incomplete | pending | — | — |
| layer3_12_real_estate_investment_tangle | incomplete | pending | — | — |
| layer3_13_emergency_medical_cascade | incomplete | pending | — | — |
| layer3_14_hidden_medical_insurance_web | incomplete | pending | — | — |
| layer3_15_identity_theft_discovery | incomplete | pending | — | — |
| layer3_16_cryptocurrency_inheritance_puzzle | incomplete | pending | — | — |
| layer3_17_environmental_contamination_cascade | incomplete | pending | — | — |
| layer3_18_genetic_testing_revelation | incomplete | pending | — | — |
| layer3_19_employment_fraud_network | incomplete | pending | — | — |
| layer3_20_medical_malpractice_pattern | incomplete | pending | — | — |
