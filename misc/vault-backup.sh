temp_file=$(mktemp)
echo "[" >${temp_file}
for item in $(vault kv list -format=json secret/ | jq -r '.[]'); do
  vault kv list -format=json secret/${item} >/dev/null 2>&1
  if [[ $? -eq 2 ]]; then
    echo "{\"${item}\": "  >>${temp_file}
    vault kv get -format=json secret/${item} | jq .data.data  >>${temp_file}
    echo "},"  >>${temp_file}
  else
    for item2 in $(vault kv list -format=json secret/${item} | jq -r '.[]'); do
      echo "going deeper for ${item}/${item2}"
      vault kv get -format=json secret/${item}/${item2} | jq .data.data  >>${temp_file}
      echo ","  >>${temp_file}
    done
  fi
done
# remove the last line of the file because itll have a trailing comma
sed -i '$ d' ${temp_file}
# put }] properly at the end since we removed the last line with the trailing comma
echo "}]" >>${temp_file}
echo ${temp_file} | jq .
#rm ${temp_file}
