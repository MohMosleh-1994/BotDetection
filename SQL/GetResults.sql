
	SELECT --TOP 10000
		C.*
		,C.Id 'CustomerId'
	INTO #tblDeleteGuests
	FROM
		Customer C (NOLOCK)
		INNER JOIN [Customer_CustomerRole_Mapping] CCRM (NOLOCK)
			ON C.Id = CCRM.Customer_Id
		LEFT JOIN [Order] O (NOLOCK)
			ON C.Id = O.CustomerId
		LEFT JOIN [Order] OB (NOLOCK)
			ON C.Id = OB.BuyerId
		LEFT JOIN [ShoppingCartItem] SCI (NOLOCK)
			ON C.Id = SCI.CustomerId
		LEFT JOIN [BlogComment] BC (NOLOCK)
			ON C.Id = BC.CustomerId
		LEFT JOIN [NewsComment] NC (NOLOCK)
			ON C.Id = NC.CustomerId
		LEFT JOIN [ProductReview] PR (NOLOCK)
			ON C.Id = PR.CustomerId
		LEFT JOIN [ProductReviewHelpfulness] PRH (NOLOCK)
			ON C.Id = PRH.CustomerId
		LEFT JOIN [PollVotingRecord] PVR (NOLOCK)
			ON C.Id = PVR.CustomerId
		LEFT JOIN [Forums_Topic] FT (NOLOCK)
			ON C.Id = FT.CustomerId
		LEFT JOIN [Forums_Post] FP (NOLOCK)
			ON C.Id = FP.CustomerId
		LEFT JOIN CustomerAddresses CA (NOLOCK)
			ON C.Id = CA.Customer_Id

		LEFT JOIN QuoteTool QT (NOLOCK)
			ON C.ID = QT.CustomerId
		LEFT JOIN BomTool BT (NOLOCK)
			ON C.ID = BT.CustomerId
	WHERE
		DATEDIFF(MINUTE, C.LastActivityDateUtc ,GETUTCDATE()) > 60
		AND	O.Id IS NULL
		AND OB.Id IS NULL
		--AND (@OnlyWithoutShoppingCart = 0 OR SCI.Id IS NULL)
		AND SCI.Id IS NULL
		AND BC.Id IS NULL
		AND NC.Id IS NULL
		AND PR.Id IS NULL
		AND PRH.Id IS NULL
		AND PVR.ID IS NULL
		AND FT.Id IS NULL
		AND FP.id IS NULL
		AND CA.Customer_Id IS NULL
		AND C.IsSystemAccount = 0
		AND QT.Id IS NULL
		AND BT.Id IS NULL
		AND CCRM.CustomerRole_Id = 4

	SELECT
		COUNT(1) 'CountOfAdminComment'
		,AdminComment
		,ISNULL(LastIpAddress ,'') 'LastIpAddress'
		,GETDATE() 'CreatedDate'
		,StoreId
	INTO #tblDeleteGuestDetailStatistic
	FROM
		#tblDeleteGuests
	GROUP BY AdminComment ,LastIpAddress ,StoreId
	HAVING COUNT(1) > 50

	SELECT
		COUNT(1) 'CountOfAdminComment'
		,AdminComment
		,ISNULL(LastIpAddress ,'') 'LastIpAddress'
		,GETDATE() 'CreatedDate'
		,StoreId
	INTO #tblDeleteGuestDetailStatisticFull
	FROM
		#tblDeleteGuests
	GROUP BY AdminComment ,LastIpAddress ,StoreId

	SELECT DISTINCT
		tblDG.Id 'CustomerId'
		,tblDG.StoreID
		,CAST(ISNULL(CASE
				WHEN LEN(tblDG.LastIpAddress) - LEN(REPLACE(tblDG.LastIpAddress, '.', '')) >= 3
					THEN ISNULL(SUBSTRING
						(
							tblDG.LastIpAddress
							,1
							,CHARINDEX('.', tblDG.LastIpAddress, CHARINDEX('.', tblDG.LastIpAddress, CHARINDEX('.', tblDG.LastIpAddress, 1) + 1) + 1) - 1
						),'')
					ELSE
						tblDG.LastIpAddress
			END ,'') AS NVARCHAR(50)) 'RangesSubnet24'
		,CAST(ISNULL(CASE
				WHEN LEN(tblDG.LastIpAddress) - LEN(REPLACE(tblDG.LastIpAddress, '.', '')) >= 3
					THEN
						ISNULL(CONCAT(PARSENAME(tblDG.LastIpAddress, 4), '.', PARSENAME(tblDG.LastIpAddress, 3)),'')
					ELSE
						tblDG.LastIpAddress
			END ,'') AS NVARCHAR(50)) 'RangesSubnet16'
		,tblDG.LastIpAddress 'IpAddress'
		,ISNULL(IAA.ASN ,'') 'ASN'
		,tblDG.CreatedOnUtc
		,tblDG.AdminComment
		,ISNULL(REPLACE(TRANSLATE(tblDG.AdminComment, '0123456789.', '           ') ,' ' ,'') ,'') 'CleanAdminComment'
		,'https://iplocation.io/ip/' + ISNULL(REPLACE(CAST(CASE WHEN tblDG.LastIpAddress NOT LIKE '%.%' THEN tblDG.LastIpAddress +'::' ELSE tblDG.LastIpAddress END AS VARCHAR(15)), ',', ''), '') 'CheckIpLink'

	FROM
		#tblDeleteGuests tblDG
		LEFT JOIN IpAddressASN IAA (NOLOCK)
			ON tblDG.LastIpAddress = IAA.IpAddress
